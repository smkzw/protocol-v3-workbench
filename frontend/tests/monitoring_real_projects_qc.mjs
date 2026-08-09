import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";


const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(process.cwd(), "records/visual_qc_20260710/monitoring_real_projects");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9376);
const runtimeExceptions = [];

const projects = [
  {
    projectId: "proj_rux_03_002",
    projectCode: "RUX-03-002",
    routeProjectId: "proj_rux_03_002",
    batchLabel: "RUX listing 2025-06-12",
    sheetCount: 53,
    subjectCount: 241,
    subjects: ["S01003", "S01017", "S03040"],
    profileMetric: "BSA总受累体表面积",
  },
  {
    projectId: "proj_my009_uc",
    projectCode: "MY009-UC",
    routeProjectId: "my009_uc_monitoring_raw",
    batchLabel: "MY009 MM Listing 2026-04-08",
    sheetCount: 61,
    subjectCount: 26,
    subjects: ["S01003", "S01008", "S01009", "S08001", "S05003"],
    sparseSubjects: ["S02002", "S16001"],
    profileMetric: "部分Mayo评分",
  },
];

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function requestJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 10000) {
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
    (listeners.get(message.method) || []).forEach((callback) => callback(message.params || {}));
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
    once(method) {
      return new Promise((resolve) => {
        const callback = (params) => {
          listeners.set(method, (listeners.get(method) || []).filter((item) => item !== callback));
          resolve(params);
        };
        listeners.set(method, [...(listeners.get(method) || []), callback]);
      });
    },
    on(method, callback) {
      listeners.set(method, [...(listeners.get(method) || []), callback]);
    },
    close() { ws.close(); },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
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
  throw new Error(`Timed out waiting for condition: ${JSON.stringify(lastValue)}`);
}

async function selectProject(cdp, projectId) {
  await waitForCondition(cdp, `
    Array.from(document.querySelectorAll('select[aria-label="选择临床研究项目"] option'))
      .some((option) => option.value === ${JSON.stringify(projectId)})
  `, 45000);
  const selected = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!selected) throw new Error(`Project switcher not found: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function clickButton(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button"))
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${label}`);
}

async function clickNav(cdp, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".nav-item"))
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Navigation button not found: ${label}`);
}

async function clickScopedButton(cdp, selector, label) {
  const clicked = await evaluate(cdp, `
    (() => {
      const root = document.querySelector(${JSON.stringify(selector)});
      const button = Array.from(root?.querySelectorAll("button") || [])
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(label)});
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Scoped button not found: ${selector}/${label}`);
}

async function selectSubject(cdp, selector, subjectId) {
  await waitForCondition(cdp, `
    Array.from(document.querySelector(${JSON.stringify(selector)})?.querySelectorAll("select") || [])
      .some((select) => Array.from(select.options).some((option) => option.value === ${JSON.stringify(subjectId)}))
  `, 45000);
  const changed = await evaluate(cdp, `
    (() => {
      const root = document.querySelector(${JSON.stringify(selector)});
      const treeButton = Array.from(root?.querySelectorAll(".profile-subject-list button") || [])
        .find((button) => button.querySelector("strong")?.textContent?.trim() === ${JSON.stringify(subjectId)});
      if (treeButton) {
        treeButton.click();
        return true;
      }
      const select = Array.from(root?.querySelectorAll("select") || [])
        .find((item) => Array.from(item.options).some((option) => option.value === ${JSON.stringify(subjectId)}));
      if (!select) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(subjectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Subject selector not found: ${selector}/${subjectId}`);
  try {
    await waitForCondition(cdp, `
      (() => {
        const root = document.querySelector(${JSON.stringify(selector)});
        if (!root) return false;
        const selectedTree = Array.from(root.querySelectorAll(".profile-subject-list button.selected strong"))
          .some((item) => item.textContent?.trim() === ${JSON.stringify(subjectId)});
        const selectedOption = Array.from(root.querySelectorAll("select"))
          .some((select) => select.value === ${JSON.stringify(subjectId)});
        const titleMatches = root.querySelector("h2")?.textContent?.includes(${JSON.stringify(subjectId)});
        return titleMatches && (selectedTree || selectedOption);
      })()
    `, 45000);
  } catch (error) {
    const state = await evaluate(cdp, `({
      activeNav: document.querySelector(".nav-item.active")?.textContent?.trim() || "",
      pageTitle: document.querySelector(${JSON.stringify(`${selector} h2`)})?.textContent?.trim() || "",
      selectedValues: Array.from(document.querySelectorAll(${JSON.stringify(`${selector} select`)})).map((item) => item.value),
      body: (document.body.textContent || "").slice(0, 2500),
    })`);
    throw new Error(`${error.message}; subjectSelectionState=${JSON.stringify(state)}; runtimeExceptions=${JSON.stringify(runtimeExceptions.slice(-5))}`);
  }
  await wait(350);
}

async function screenshot(cdp, filename) {
  await cdp.send("Runtime.evaluate", { expression: "window.scrollTo(0, 0)" });
  await wait(200);
  const image = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  const outputPath = path.join(outputDir, filename);
  await writeFile(outputPath, Buffer.from(image.data, "base64"));
  return outputPath;
}

async function monitoringMetrics(cdp, project) {
  return evaluate(cdp, `
    (() => {
      const root = document.querySelector(".monitoring-page");
      const text = root?.textContent || "";
      const html = (root?.outerHTML || "").toLowerCase();
      const doc = document.documentElement;
      const body = document.body;
      const layout = document.querySelector(".monitoring-layout");
      const ledger = document.querySelector(".ledger-panel");
      const detail = document.querySelector(".risk-detail");
      const rect = (element) => element ? {
        x: Math.round(element.getBoundingClientRect().x),
        width: Math.round(element.getBoundingClientRect().width),
        height: Math.round(element.getBoundingClientRect().height),
      } : null;
      return {
        projectId: document.querySelector('select[aria-label="选择临床研究项目"]')?.value,
        riskRowCount: document.querySelectorAll(".risk-card-row").length,
        hasRawCounts: text.includes(${JSON.stringify(`${project.sheetCount} 个数据表`)}),
        hasCmIpBoundary: text.includes("CM/CM1仅作为非试验用药") && text.includes("试验药物变更"),
        hasRiskDetail: Boolean(detail && detail.textContent.includes("证据链") && detail.textContent.includes("医学处置闭环")),
        hasSubjectEntryButtons: text.includes("进入 Subject Timeline") && text.includes("进入 Patient Profile"),
        noDemoSubjectLeak: !["10008", "06021", "10021", "10045", "10031"].some((token) => text.includes(token)),
        noCrossProjectText: ${JSON.stringify(project.projectId === "proj_my009_uc")} ? !text.includes("RUX-03-002") : !text.includes("MY009-UC"),
        noLocalPathLeak: !["/users/", "file://", "file_path", "server_path", "storage_key"].some((token) => html.includes(token)),
        noLifecycleNumbering: !/第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]/.test(text),
        noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
        layoutColumns: layout ? getComputedStyle(layout).gridTemplateColumns : "",
        ledgerRect: rect(ledger),
        detailRect: rect(detail),
      };
    })()
  `);
}

async function timelineMetrics(cdp, project, subjectId) {
  return evaluate(cdp, `
    (() => {
      const root = document.querySelector(".reference-timeline-page");
      const text = root?.textContent || "";
      const html = (root?.outerHTML || "").toLowerCase();
      const doc = document.documentElement;
      const body = document.body;
      const select = root?.querySelector("select");
      const options = Array.from(select?.options || []).map((option) => option.value);
      const blocks = Array.from(root?.querySelectorAll(".reference-svg-event-block") || []);
      const categoryClass = (item) => Array.from(item.classList).find((name) => name.startsWith("event-category-")) || "";
      return {
        subjectId: ${JSON.stringify(subjectId)},
        selectedSubject: select?.value,
        subjectOptionCount: options.length,
        expectedSubjectCount: ${project.subjectCount},
        hasVisitAxis: Boolean(root?.querySelector(".reference-svg-axis")),
        hasCmLane: text.includes("合并用药（非试验用药）"),
        hasIpLane: text.includes("试验药物变更"),
        hasAeLane: text.includes("AE"),
        eventBlockCount: blocks.length,
        categoryCount: new Set(blocks.map(categoryClass).filter(Boolean)).size,
        distinctFillCount: new Set(blocks.map((block) => getComputedStyle(block).fill)).size,
        noDemoSubjectLeak: !options.some((value) => ["10008", "06021", "10021", "10045", "10031"].includes(value)),
        noLocalPathLeak: !["/users/", "file://", "file_path", "server_path", "storage_key"].some((token) => html.includes(token)),
        noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
      };
    })()
  `);
}

async function profileMetrics(cdp, project, subjectId) {
  return evaluate(cdp, `
    (() => {
      const root = document.querySelector(".patient-profile-page");
      const text = root?.textContent || "";
      const html = (root?.outerHTML || "").toLowerCase();
      const doc = document.documentElement;
      const body = document.body;
      return {
        subjectId: ${JSON.stringify(subjectId)},
        hasSubject: text.includes(${JSON.stringify(subjectId)}),
        hasExpectedMetric: text.includes(${JSON.stringify(project.profileMetric)}),
        hasAlt: text.includes("ALT"),
        hasAst: text.includes("AST"),
        trendChartCount: root?.querySelectorAll(".profile-trend-chart").length || root?.querySelectorAll("svg").length || 0,
        hasSourceIndex: text.includes("关联事件索引"),
        hasBlindedArm: text.includes("待解盲"),
        noLocalPathLeak: !["/users/", "file://", "file_path", "server_path", "storage_key"].some((token) => html.includes(token)),
        noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
      };
    })()
  `);
}

async function sparseProfileMetrics(cdp, subjectId) {
  return evaluate(cdp, `
    (() => {
      const root = document.querySelector(".patient-profile-page");
      const text = root?.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      return {
        subjectId: ${JSON.stringify(subjectId)},
        hasSubject: text.includes(${JSON.stringify(subjectId)}),
        hasEfficacyEmptyState: text.includes("等待生成疗效趋势"),
        hasSafetyEmptyState: text.includes("等待生成安全性趋势"),
        noInventedDemographics: !text.includes("性别：") && !text.includes("年龄："),
        noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
      };
    })()
  `);
}

async function captureProject(cdp, project) {
  await selectProject(cdp, project.projectId);
  await waitForCondition(cdp, `document.querySelector(".topbar")?.textContent.includes(${JSON.stringify(project.projectCode)})`);
  await waitForCondition(cdp, `!document.body.textContent.includes("项目未加载")`);
  await wait(500);
  await clickNav(cdp, "医学监查");
  try {
    await waitForCondition(cdp, `document.querySelector(".monitoring-page")?.textContent.includes("原始数据批次驱动的风险复核")`);
  } catch (error) {
    const state = await evaluate(cdp, `({
      selectedProject: document.querySelector('select[aria-label="选择临床研究项目"]')?.value,
      activeNav: document.querySelector(".nav-item.active")?.textContent?.trim() || "",
      body: (document.body.textContent || "").slice(0, 3500),
    })`);
    throw new Error(`${error.message}; monitoringNavigationState=${JSON.stringify(state)}`);
  }
  await waitForCondition(cdp, `document.querySelectorAll(".risk-card-row").length > 0`, 45000);
  await waitForCondition(cdp, `document.querySelector(".monitoring-raw-intake")?.textContent.includes(${JSON.stringify(`${project.sheetCount} 个数据表`)})`, 45000);
  const monitoring = await monitoringMetrics(cdp, project);
  const monitoringScreenshot = await screenshot(cdp, `monitoring_${project.projectId}_desktop.png`);

  await clickButton(cdp, "进入 Subject Timeline");
  await waitForCondition(cdp, `Boolean(document.querySelector(".reference-timeline-page"))`, 45000);
  const timelines = [];
  for (const subjectId of project.subjects) {
    await selectSubject(cdp, ".reference-timeline-page", subjectId);
    await waitForCondition(cdp, `document.querySelector(".reference-timeline-page")?.textContent.includes(${JSON.stringify(subjectId)})`);
    timelines.push(await timelineMetrics(cdp, project, subjectId));
  }
  await selectSubject(cdp, ".reference-timeline-page", project.subjects[0]);
  const timelineScreenshot = await screenshot(cdp, `timeline_${project.projectId}_${project.subjects[0]}_desktop.png`);
  await clickButton(cdp, "返回医学监查");
  await waitForCondition(cdp, `Boolean(document.querySelector(".monitoring-page"))`);

  await clickButton(cdp, "进入 Patient Profile");
  await waitForCondition(cdp, `Boolean(document.querySelector(".patient-profile-page"))`, 45000);
  await clickScopedButton(cdp, ".profile-filter-bar", "全部");
  await waitForCondition(cdp, `document.querySelector(".patient-profile-page select")?.options.length === ${project.subjectCount}`, 45000);
  const profiles = [];
  for (const subjectId of project.subjects) {
    await selectSubject(cdp, ".patient-profile-page", subjectId);
    await waitForCondition(cdp, `document.querySelector(".patient-profile-page")?.textContent.includes(${JSON.stringify(project.profileMetric)})`, 45000);
    profiles.push(await profileMetrics(cdp, project, subjectId));
  }
  const sparseProfiles = [];
  let sparseProfileScreenshot = null;
  for (const subjectId of project.sparseSubjects || []) {
    await selectSubject(cdp, ".patient-profile-page", subjectId);
    await waitForCondition(cdp, `document.querySelector(".patient-profile-page")?.textContent.includes(${JSON.stringify(subjectId)})`, 45000);
    await waitForCondition(cdp, `document.querySelector(".patient-profile-page")?.textContent.includes("等待生成疗效趋势")`, 45000);
    sparseProfiles.push(await sparseProfileMetrics(cdp, subjectId));
    if (!sparseProfileScreenshot) {
      sparseProfileScreenshot = await screenshot(cdp, `profile_${project.projectId}_${subjectId}_sparse_desktop.png`);
    }
  }
  await selectSubject(cdp, ".patient-profile-page", project.subjects[0]);
  await waitForCondition(cdp, `document.querySelector(".patient-profile-page")?.textContent.includes(${JSON.stringify(project.profileMetric)})`, 45000);
  const profileScreenshot = await screenshot(cdp, `profile_${project.projectId}_${project.subjects[0]}_desktop.png`);
  return {
    project,
    monitoring,
    timelines,
    profiles,
    sparseProfiles,
    screenshots: { monitoringScreenshot, timelineScreenshot, profileScreenshot, sparseProfileScreenshot },
  };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "monitoring-real-projects-qc-"));
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
    cdp.on("Runtime.exceptionThrown", (event) => {
      runtimeExceptions.push({
        text: event.exceptionDetails?.text || "",
        description: event.exceptionDetails?.exception?.description || "",
        url: event.exceptionDetails?.url || "",
        lineNumber: event.exceptionDetails?.lineNumber,
        columnNumber: event.exceptionDetails?.columnNumber,
      });
    });
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    const loaded = cdp.once("Page.loadEventFired");
    await cdp.send("Page.navigate", { url: appUrl });
    await loaded;
    await waitForCondition(cdp, `Boolean(document.querySelector('select[aria-label="选择临床研究项目"]'))`, 45000);

    const results = [];
    for (const project of projects) results.push(await captureProject(cdp, project));
    cdp.close();

    const failures = [];
    for (const result of results) {
      const { project, monitoring, timelines, profiles, sparseProfiles } = result;
      for (const [key, value] of Object.entries(monitoring)) {
        if (key.startsWith("has") || key.startsWith("no")) {
          if (!value) failures.push(`${project.projectId}/monitoring:${key}`);
        }
      }
      if (monitoring.riskRowCount < 1) failures.push(`${project.projectId}/monitoring:no risks`);
      if (!monitoring.ledgerRect || !monitoring.detailRect || monitoring.detailRect.width <= monitoring.ledgerRect.width * 0.9) {
        failures.push(`${project.projectId}/monitoring:risk detail is not visually primary`);
      }
      for (const item of timelines) {
        for (const [key, value] of Object.entries(item)) {
          if (key.startsWith("has") || key.startsWith("no")) {
            if (!value) failures.push(`${project.projectId}/${item.subjectId}/timeline:${key}`);
          }
        }
        if (item.subjectOptionCount !== project.subjectCount) failures.push(`${project.projectId}/${item.subjectId}/timeline:subject count ${item.subjectOptionCount}`);
        if (item.eventBlockCount < 1 || item.categoryCount < 2 || item.distinctFillCount < 2) failures.push(`${project.projectId}/${item.subjectId}/timeline:insufficient visual event categories`);
      }
      for (const item of profiles) {
        for (const [key, value] of Object.entries(item)) {
          if (key.startsWith("has") || key.startsWith("no")) {
            if (!value) failures.push(`${project.projectId}/${item.subjectId}/profile:${key}`);
          }
        }
        if (item.trendChartCount < 3) failures.push(`${project.projectId}/${item.subjectId}/profile:insufficient trend charts`);
      }
      for (const item of sparseProfiles) {
        for (const [key, value] of Object.entries(item)) {
          if (key.startsWith("has") || key.startsWith("no")) {
            if (!value) failures.push(`${project.projectId}/${item.subjectId}/sparse-profile:${key}`);
          }
        }
      }
    }
    const reportPath = path.join(outputDir, "monitoring_real_projects_qc.json");
    await writeFile(reportPath, `${JSON.stringify({ appUrl, viewport: { width: 1600, height: 1000 }, results, failures }, null, 2)}\n`);
    if (failures.length) throw new Error(`Monitoring real-project QC failed: ${failures.join("; ")}. Report: ${reportPath}`);
    console.log(reportPath);
  } finally {
    if (chrome.exitCode === null) {
      const exited = new Promise((resolve) => chrome.once("exit", resolve));
      chrome.kill("SIGTERM");
      await Promise.race([exited, wait(3000)]);
    }
    await wait(200);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
