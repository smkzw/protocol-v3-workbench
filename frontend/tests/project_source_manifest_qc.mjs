import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "../records/active_slices/project_source_manifest_20260709/visual_qc");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9388);

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
    (listeners.get(message.method) || []).forEach((callback) => callback(message.params || {}));
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
    once(method) {
      return new Promise((resolve) => {
        const callback = (params) => {
          const callbacks = listeners.get(method) || [];
          listeners.set(method, callbacks.filter((item) => item !== callback));
          resolve(params);
        };
        listeners.set(method, [...(listeners.get(method) || []), callback]);
      });
    },
    close() {
      ws.close();
    },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.exception?.value || result.exceptionDetails.text;
    throw new Error(detail || "Runtime evaluation failed");
  }
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, expression)) return true;
    await wait(250);
  }
  return false;
}

async function clickByText(cdp, selector, text) {
  await evaluate(cdp, `
    (() => {
      const target = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
        .find((item) => (item.textContent || "").includes(${JSON.stringify(text)}));
      if (!target) throw new Error("Missing " + ${JSON.stringify(selector)} + " text: " + ${JSON.stringify(text)});
      target.click();
      return true;
    })()
  `);
}

async function selectProject(cdp, projectId) {
  await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) throw new Error("Missing canonical project selector");
      if (!Array.from(select.options).some((option) => option.value === ${JSON.stringify(projectId)})) {
        throw new Error("Missing project option: " + ${JSON.stringify(projectId)});
      }
      select.value = ${JSON.stringify(projectId)};
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
}

async function capture(cdp, name) {
  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
  });
  const screenshotPath = path.join(outputDir, `${name}.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return screenshotPath;
}

async function removeWithRetry(targetPath, retries = 5) {
  for (let attempt = 0; attempt < retries; attempt += 1) {
    try {
      await rm(targetPath, { recursive: true, force: true });
      return;
    } catch (error) {
      if (attempt === retries - 1) throw error;
      await wait(250 * (attempt + 1));
    }
  }
}

async function pageMetrics(cdp, label) {
  return evaluate(cdp, `
    (() => {
      const topbarText = document.querySelector(".topbar")?.textContent || "";
      const bodyText = document.body.textContent || "";
      const subjectOptionValues = Array.from(document.querySelectorAll("main.page select option"))
        .map((option) => option.value || (option.textContent || "").split("|")[0].trim());
      const doc = document.documentElement;
      const body = document.body;
      const sourceLeakPattern = /\\/Users\\/|file:\\/\\/|root_path|file_path|absolute_path|allowed_roots|content_hash|preview_hash|storage_key|server_path|source_path/i;
      return {
        label: ${JSON.stringify(label)},
        topbarText,
        bodyHasMgk10: bodyText.includes("MG-K10-SAR-DEMO"),
        bodyHasD001: bodyText.includes("CMS-D001") || bodyText.includes("D001"),
        bodyHasRux: bodyText.includes("RUX-03-002"),
        bodyHasMy009: bodyText.includes("MY009"),
        hasCurrentSource: topbarText.includes("当前来源"),
        hasCrossSource: topbarText.includes("跨项目源"),
        hasDemoSubjectLeak: subjectOptionValues.includes("10008") || subjectOptionValues.includes("06021"),
        subjectOptionValues: subjectOptionValues.slice(0, 30),
        hasInternalSourceLeak: sourceLeakPattern.test(document.body.outerHTML),
        hasInternalAgentLabel: bodyText.includes("Codex"),
        overflowX: Math.max(doc.scrollWidth, body.scrollWidth) > window.innerWidth + 1,
      };
    })()
  `);
}

function assertCondition(condition, message, context) {
  if (!condition) {
    throw new Error(`${message}: ${JSON.stringify(context, null, 2)}`);
  }
}

async function run() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "workbench-source-manifest-qc-"));
  const chrome = spawn(chromePath, [
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "about:blank",
  ], { stdio: "ignore" });

  let cdp;
  try {
    let target;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      try {
        const tabs = await fetch(`http://127.0.0.1:${debugPort}/json`).then((response) => response.json());
        target = Array.isArray(tabs) ? tabs.find((tab) => tab.type === "page" && tab.webSocketDebuggerUrl) : null;
        if (target) break;
      } catch {
        await wait(150);
      }
    }
    if (!target?.webSocketDebuggerUrl) throw new Error("Chrome CDP page target not available");

    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });

    const loaded = cdp.once("Page.loadEventFired");
    await cdp.send("Page.navigate", { url: appUrl });
    await loaded;
    if (!(await waitForCondition(cdp, `document.querySelector('.project-switcher select')?.value === "proj_rux_03_002" && document.querySelector(".topbar")?.textContent.includes("RUX-03-002") && document.querySelector(".topbar")?.textContent.includes("当前来源") && document.querySelectorAll('.module-row').length >= 6`, 60000))) {
      throw new Error("Overview did not load project/source context");
    }

    const results = [];
    const overview = await pageMetrics(cdp, "overview");
    overview.screenshotPath = await capture(cdp, "overview_source_manifest");
    assertCondition(overview.topbarText.includes("RUX-03-002"), "Overview topbar missing canonical RUX project", overview);
    assertCondition(overview.topbarText.includes("项目总看板"), "Overview current source should be dashboard", overview);
    assertCondition(!overview.hasCrossSource, "Overview should not be marked as cross-project", overview);
    assertCondition(!overview.hasInternalSourceLeak, "Overview leaked internal source config", overview);
    assertCondition(!overview.hasInternalAgentLabel, "Overview exposed an internal agent/runtime label", overview);
    assertCondition(!overview.overflowX, "Overview body overflowed horizontally", overview);
    results.push(overview);

    await clickByText(cdp, "button", "医学监查");
    if (!(await waitForCondition(cdp, `document.querySelector(".topbar")?.textContent.includes("RUX-03-002") && (document.body.textContent.includes("真实监查风险锚点") || document.body.textContent.includes("待医学复核")) && document.body.textContent.includes("180793 行 listing")`, 60000))) {
      const debug = await pageMetrics(cdp, "medical_monitoring_debug");
      debug.screenshotPath = await capture(cdp, "monitoring_source_manifest_debug");
      throw new Error(`Monitoring page did not load RUX source context and inbox: ${JSON.stringify(debug, null, 2)}`);
    }
    const monitoring = await pageMetrics(cdp, "medical_monitoring");
    monitoring.screenshotPath = await capture(cdp, "monitoring_source_manifest");
    assertCondition(monitoring.topbarText.includes("医学监查"), "Monitoring current source missing module label", monitoring);
    assertCondition(monitoring.topbarText.includes("RUX-03-002"), "Monitoring current source missing RUX", monitoring);
    assertCondition(monitoring.topbarText.includes("RUX listing 2025-06-12"), "Monitoring data batch still follows canonical dashboard instead of RUX source", monitoring);
    assertCondition(!monitoring.hasCrossSource, "Monitoring must remain in the selected canonical project", monitoring);
    assertCondition(monitoring.bodyHasRux, "Monitoring page body missing RUX source content", monitoring);
    assertCondition(!monitoring.hasInternalSourceLeak, "Monitoring page leaked internal source config", monitoring);
    assertCondition(!monitoring.overflowX, "Monitoring body overflowed horizontally", monitoring);
    results.push(monitoring);

    await clickByText(cdp, "button", "进入 Subject Timeline");
    if (!(await waitForCondition(cdp, `document.querySelector(".topbar")?.textContent.includes("RUX-03-002") && document.body.textContent.includes("AE 明细")`))) {
      throw new Error("Subject Timeline did not keep RUX source context");
    }
    const timeline = await pageMetrics(cdp, "subject_timeline");
    timeline.screenshotPath = await capture(cdp, "timeline_source_manifest");
    assertCondition(timeline.topbarText.includes("RUX-03-002"), "Timeline topbar missing RUX source", timeline);
    assertCondition(!timeline.hasDemoSubjectLeak, "Timeline rendered demo subjects under RUX source", timeline);
    assertCondition(!timeline.overflowX, "Timeline body overflowed horizontally", timeline);
    results.push(timeline);

    await clickByText(cdp, "button", "数据分析与TFL");
    if (!(await waitForCondition(cdp, `document.querySelector(".topbar")?.textContent.includes("RUX-03-002") && document.body.textContent.includes("RUX-03-002 ADaM/SDTM")`, 60000))) {
      throw new Error("TFL page did not load project-scoped RUX package");
    }
    const tfl = await pageMetrics(cdp, "tfl");
    tfl.screenshotPath = await capture(cdp, "tfl_project_scoped");
    tfl.bodyHasMy008Package = await evaluate(cdp, `document.body.textContent.includes("MY008211A-PNH-3-01 SAP/TFL最终交付包")`);
    assertCondition(!tfl.bodyHasMy008Package, "RUX TFL surface leaked MY008 package", tfl);
    assertCondition(!tfl.overflowX, "TFL body overflowed horizontally", tfl);
    results.push(tfl);

    await clickByText(cdp, "button", "医学写作");
    if (!(await waitForCondition(cdp, `document.body.textContent.includes("当前真实项目仅完成来源与章节候选解析") && document.body.textContent.includes("RUX-03-002研究方案写作资料包")`, 60000))) {
      throw new Error("RUX writing page did not fail closed on missing editable document session");
    }
    const writing = await pageMetrics(cdp, "writing");
    writing.screenshotPath = await capture(cdp, "writing_project_scoped_blocked_editor");
    writing.hasDemoEditorBody = await evaluate(cdp, `document.body.textContent.includes("rTNSS 总分较基线的变化")`);
    assertCondition(!writing.hasDemoEditorBody, "RUX writing surface leaked MG-K10 demo editor body", writing);
    assertCondition(!writing.overflowX, "Writing body overflowed horizontally", writing);
    results.push(writing);

    await selectProject(cdp, "proj_d001");
    if (!(await waitForCondition(cdp, `document.querySelector('.project-switcher select')?.value === "proj_d001" && document.querySelector(".topbar")?.textContent.includes("CMS-D001")`, 60000))) {
      throw new Error("Canonical project switch to D001 failed");
    }
    await clickByText(cdp, "button", "入排审核");
    if (!(await waitForCondition(cdp, `document.querySelector(".topbar")?.textContent.includes("CMS-D001") && document.body.textContent.includes("原始资料链路") && document.body.textContent.includes("143") && document.body.textContent.includes("1524")`, 60000))) {
      throw new Error("Eligibility page did not load D001 source context");
    }
    const eligibility = await pageMetrics(cdp, "eligibility");
    eligibility.screenshotPath = await capture(cdp, "eligibility_source_manifest");
    eligibility.eligibilityBody = await evaluate(cdp, `
      (() => {
        const primaryText = [
          ".eligibility-subjects-panel",
          ".eligibility-review-panel",
          ".rule-tree",
        ].map((selector) => document.querySelector(selector)?.textContent || "").join("\\n");
        const legacyText = document.querySelector(".legacy-comparison")?.textContent || "";
        return {
          primaryHasLegacyMgk10: /MG-K10-SAR-III|enrollment-review-app/.test(primaryText),
          primaryHasRawPending: primaryText.includes("候选受试者池（原始资料发现）") && primaryText.includes("逐条入排审核待生成"),
          primaryHasRawTaskPlan: primaryText.includes("当前方案规则抽取任务"),
          legacyComparisonVisible: legacyText.includes("历史系统对照") && legacyText.includes("不得用于当前 D001/MY009 原始资料审核输入"),
          hasRawEngineeringLabels: /\braw\b|legacy|source_registry/.test(document.body.textContent || ""),
        };
      })()
    `);
    assertCondition(eligibility.topbarText.includes("入排审核"), "Eligibility current source missing module label", eligibility);
    assertCondition(eligibility.topbarText.includes("CMS-D001"), "Eligibility current source missing D001", eligibility);
    assertCondition(eligibility.topbarText.includes("D001 全量入组资料"), "Eligibility data batch still follows canonical dashboard instead of D001 source", eligibility);
    assertCondition(!eligibility.hasCrossSource, "Eligibility must remain in the selected canonical D001 project", eligibility);
    assertCondition(!eligibility.eligibilityBody.primaryHasLegacyMgk10, "Eligibility primary body still renders legacy MG-K10/enrollment-review-app results", eligibility);
    assertCondition(eligibility.eligibilityBody.primaryHasRawPending, "Eligibility primary body missing raw-source pending-review state", eligibility);
    assertCondition(eligibility.eligibilityBody.primaryHasRawTaskPlan, "Eligibility primary body missing current raw task plan", eligibility);
    assertCondition(eligibility.eligibilityBody.legacyComparisonVisible, "Eligibility legacy comparison boundary missing", eligibility);
    assertCondition(!eligibility.eligibilityBody.hasRawEngineeringLabels, "Eligibility exposed raw engineering labels", eligibility);
    assertCondition(!eligibility.hasDemoSubjectLeak, "D001 eligibility leaked monitoring demo subjects", eligibility);
    assertCondition(!eligibility.overflowX, "Eligibility body overflowed horizontally", eligibility);
    results.push(eligibility);

    await clickByText(cdp, "button", "数据分析与TFL");
    if (!(await waitForCondition(cdp, `document.body.textContent.includes("功能未配置") && document.body.textContent.includes("当前项目尚未配置该模块的真实来源与执行链路")`))) {
      throw new Error("D001 unconfigured TFL route did not fail closed");
    }
    const d001UnconfiguredTfl = await pageMetrics(cdp, "d001_unconfigured_tfl");
    d001UnconfiguredTfl.hasRuxPackage = await evaluate(cdp, `document.body.textContent.includes("RUX-03-002 ADaM/SDTM")`);
    assertCondition(!d001UnconfiguredTfl.hasRuxPackage, "D001 unconfigured TFL page leaked RUX package", d001UnconfiguredTfl);
    assertCondition(!d001UnconfiguredTfl.overflowX, "D001 unconfigured TFL page overflowed horizontally", d001UnconfiguredTfl);
    results.push(d001UnconfiguredTfl);

    await selectProject(cdp, "proj_my009_uc");
    if (!(await waitForCondition(cdp, `document.querySelector('.project-switcher select')?.value === "proj_my009_uc" && document.querySelector(".topbar")?.textContent.includes("MY009-UC")`, 60000))) {
      throw new Error("Canonical project switch to MY009 failed");
    }
    await clickByText(cdp, "button", "安全信号与PV协同");
    if (!(await waitForCondition(cdp, `document.querySelector(".topbar")?.textContent.includes("MY009-UC")`))) {
      throw new Error("Safety/PV page did not load MY009 source context");
    }
    const safety = await pageMetrics(cdp, "safety_pv");
    safety.screenshotPath = await capture(cdp, "safety_source_manifest");
    assertCondition(safety.topbarText.includes("安全信号与PV协同"), "Safety/PV current source missing module label", safety);
    assertCondition(safety.topbarText.includes("MY009-UC"), "Safety/PV source missing MY009", safety);
    assertCondition(safety.topbarText.includes("MY009 S1/PV 2026-04"), "Safety/PV data batch still follows canonical dashboard instead of MY009 source", safety);
    safety.hasRuxSafetyPackage = await evaluate(cdp, `document.body.textContent.includes("RUX-03-002 PV计划与临床安全性总结")`);
    assertCondition(!safety.hasRuxSafetyPackage, "MY009 Safety/PV surface leaked RUX package", safety);
    assertCondition(!safety.hasCrossSource, "Safety/PV must remain in selected canonical MY009 project", safety);
    assertCondition(!safety.overflowX, "Safety/PV body overflowed horizontally", safety);
    results.push(safety);

    await selectProject(cdp, "proj_mgk10_crswnp");
    if (!(await waitForCondition(cdp, `document.querySelector('.project-switcher select')?.value === "proj_mgk10_crswnp" && document.querySelector(".topbar")?.textContent.includes("MG-K10-CRSwNP")`, 60000))) {
      throw new Error("Canonical project switch to MG-K10 CRSwNP failed");
    }
    await clickByText(cdp, "button", "证据调研与方案设计");
    if (!(await waitForCondition(cdp, `document.body.textContent.includes("CRSwNP竞品证据与方案设计资料包")`, 60000))) {
      throw new Error("CRSwNP evidence page did not load project-scoped evidence package");
    }
    const evidence = await pageMetrics(cdp, "evidence_design");
    evidence.screenshotPath = await capture(cdp, "evidence_project_scoped");
    assertCondition(!evidence.hasCrossSource, "Evidence page must remain in selected canonical CRSwNP project", evidence);
    assertCondition(!evidence.overflowX, "Evidence body overflowed horizontally", evidence);
    results.push(evidence);

    const metricsPath = path.join(outputDir, "project_source_manifest_qc_metrics.json");
    await writeFile(metricsPath, JSON.stringify({ appUrl, results }, null, 2), "utf8");
    console.log(JSON.stringify({ metricsPath, results }, null, 2));
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(500);
    await removeWithRetry(userDataDir);
  }
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
