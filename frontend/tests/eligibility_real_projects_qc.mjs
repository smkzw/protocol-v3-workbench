import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(scriptDir, "../../records/visual_qc_20260710");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9375);
const projects = [
  { projectId: "proj_d001", projectCode: "CMS-D001", targetSubject: "SA07005", minimumSubjects: 100, expectedInclusion: 6, expectedExclusion: 30 },
  { projectId: "proj_my009_uc", projectCode: "MY009-UC", targetSubject: "S01009", minimumSubjects: 5, expectedInclusion: 10, expectedExclusion: 24 },
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

async function selectProject(cdp, project) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, ${JSON.stringify(project.projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project switcher not found: ${project.projectId}`);
  await waitForCondition(cdp, `
    (() => {
      return document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(project.projectId)}
        && !document.querySelector(".source-context-unconfigured");
    })()
  `, 30000);
}

async function captureProject(cdp, project) {
  await selectProject(cdp, project);
  await clickNav(cdp, "入排审核");
  await waitForCondition(cdp, `
    document.body.textContent.includes("候选受试者池（原始资料发现）") &&
    Array.from(document.querySelectorAll(".eligibility-subject-table .subject-link"))
      .some((item) => (item.textContent || "").trim() === ${JSON.stringify(project.targetSubject)})
  `, 45000);

  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".eligibility-subject-table .subject-link"))
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(project.targetSubject)});
      if (!button) return false;
      button.scrollIntoView({ block: "center" });
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Subject button not found: ${project.targetSubject}`);
  await waitForCondition(cdp, `
    document.querySelector(".eligibility-review-panel")?.textContent.includes(${JSON.stringify(project.targetSubject)}) &&
    document.querySelectorAll(".eligibility-review-panel .rule-review-table tbody tr").length > 0 &&
    document.querySelector(".eligibility-rule-tree-scroll")?.textContent.includes("IN-01")
  `, 30000);

  const protocolRules = await requestJson(new URL(`/api/projects/${project.projectId}/eligibility/protocol-rules`, appUrl));
  const protocolRulesJson = JSON.stringify(protocolRules);
  const lowerProtocolRulesJson = protocolRulesJson.toLowerCase();
  const exclusionTabClicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".eligibility-rule-tabs button"))
        .find((item) => (item.textContent || "").includes("排除 EX"));
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!exclusionTabClicked) throw new Error(`Exclusion rule tab not found: ${project.projectId}`);
  await waitForCondition(cdp, `document.querySelector(".eligibility-rule-tree-scroll")?.textContent.includes("EX-01")`);
  const inclusionTabClicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll(".eligibility-rule-tabs button"))
        .find((item) => (item.textContent || "").includes("入选 IN"));
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!inclusionTabClicked) throw new Error(`Inclusion rule tab not found: ${project.projectId}`);
  await waitForCondition(cdp, `document.querySelector(".eligibility-rule-tree-scroll")?.textContent.includes("IN-01")`);

  const metrics = await evaluate(cdp, `
    (() => {
      const text = document.body.textContent || "";
      const doc = document.documentElement;
      const body = document.body;
      const workbench = document.querySelector(".eligibility-workbench");
      const tableWrap = document.querySelector(".eligibility-subjects-panel .eligibility-table-wrap");
      const subjectsPanel = document.querySelector(".eligibility-subjects-panel");
      const reviewPanel = document.querySelector(".eligibility-review-panel");
      const sidePanel = document.querySelector(".eligibility-side");
      const ruleTreeScroll = document.querySelector(".eligibility-rule-tree-scroll");
      const rect = (element) => element ? {
        x: Math.round(element.getBoundingClientRect().x),
        y: Math.round(element.getBoundingClientRect().y),
        width: Math.round(element.getBoundingClientRect().width),
        height: Math.round(element.getBoundingClientRect().height),
      } : null;
      const candidateCells = Array.from(document.querySelectorAll(".eligibility-subject-table td"));
      const workbenchHtml = document.querySelector(".eligibility-workbench")?.outerHTML || "";
      const lowerWorkbenchHtml = workbenchHtml.toLowerCase();
      return {
        viewport: { width: window.innerWidth, height: window.innerHeight },
        projectId: document.querySelector('select[aria-label="选择临床研究项目"]')?.value,
        subjectRows: document.querySelectorAll(".eligibility-subject-table tbody tr").length,
        sourceRows: document.querySelectorAll(".eligibility-review-panel .rule-review-table tbody tr").length,
        selectedSubjectVisible: document.querySelector(".eligibility-review-panel")?.textContent.includes(${JSON.stringify(project.targetSubject)}) || false,
        hasPendingBoundary: text.includes("当前不输出入排结论") && text.includes("待独立AI与医学确认"),
        hasProtocolRuleTask: text.includes("方案 IN/EX 规则抽取"),
        hasActualInclusionRule: Boolean(ruleTreeScroll?.textContent.includes("IN-01")),
        hasExpectedRuleCounts: text.includes(${JSON.stringify(`入选 IN · ${project.expectedInclusion}`)}) && text.includes(${JSON.stringify(`排除 EX · ${project.expectedExclusion}`)}),
        hasProtocolRuleSource: Boolean(document.querySelector(".eligibility-rule-source")?.textContent.includes("docx:paragraph:")),
        hasSourceInventory: text.includes("原始资料清单") && text.includes("来源ID"),
        noConclusionLabelLeak: !text.includes("阳性导致筛败") && !text.includes("V3筛败"),
        noPathLeak: !["/users/", "file://", "relative_path", "root_path", "absolute_path", "server_path", "filename"]
          .some((token) => lowerWorkbenchHtml.includes(token)),
        noLifecycleNumbering: !/第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]/.test(text),
        noPageOverflowX: Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1,
        candidateCellOverflowCount: candidateCells.filter((cell) => cell.scrollWidth > cell.clientWidth + 1).length,
        workbenchColumns: workbench ? getComputedStyle(workbench).gridTemplateColumns : "",
        workbenchAreas: workbench ? getComputedStyle(workbench).gridTemplateAreas : "",
        subjectsRect: rect(subjectsPanel),
        reviewRect: rect(reviewPanel),
        sideRect: rect(sidePanel),
        ruleTreeNodeCount: document.querySelectorAll(".eligibility-rule-tree-scroll .eligibility-rule-node").length,
        ruleTreeScroll: ruleTreeScroll ? {
          clientHeight: ruleTreeScroll.clientHeight,
          scrollHeight: ruleTreeScroll.scrollHeight,
          overflowY: getComputedStyle(ruleTreeScroll).overflowY,
        } : null,
        subjectTableScroll: tableWrap ? {
          clientHeight: tableWrap.clientHeight,
          scrollHeight: tableWrap.scrollHeight,
          overflowY: getComputedStyle(tableWrap).overflowY,
        } : null,
      };
    })()
  `);
  await cdp.send("Runtime.evaluate", { expression: "window.scrollTo(0, 0)" });
  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  const screenshotPath = path.join(outputDir, `eligibility_${project.projectId}_desktop.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return {
    project,
    protocolRuleAudit: {
      inclusionCount: protocolRules.counts?.inclusion,
      exclusionCount: protocolRules.counts?.exclusion,
      firstInclusionRuleId: protocolRules.inclusion?.rules?.[0]?.rule_id,
      firstExclusionRuleId: protocolRules.exclusion?.rules?.[0]?.rule_id,
      inclusionSourceLocator: protocolRules.inclusion?.source_locator,
      exclusionSourceLocator: protocolRules.exclusion?.source_locator,
      noPublicPathOrHashLeak: !["/users/", "file://", "content_hash", "word_numbering", "absolute_path", "server_path"]
        .some((token) => lowerProtocolRulesJson.includes(token)),
    },
    metrics,
    screenshotPath,
  };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "eligibility-real-qc-"));
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
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    const results = [];
    for (const project of projects) results.push(await captureProject(cdp, project));
    const failures = [];
    for (const result of results) {
      const { project, metrics, protocolRuleAudit } = result;
      if (metrics.projectId !== project.projectId) failures.push(`${project.projectId}:projectId`);
      if (metrics.subjectRows < project.minimumSubjects) failures.push(`${project.projectId}:subjectRows`);
      if (metrics.sourceRows < 1) failures.push(`${project.projectId}:sourceRows`);
      for (const key of [
        "selectedSubjectVisible",
        "hasPendingBoundary",
        "hasProtocolRuleTask",
        "hasActualInclusionRule",
        "hasExpectedRuleCounts",
        "hasProtocolRuleSource",
        "hasSourceInventory",
        "noConclusionLabelLeak",
        "noPathLeak",
        "noLifecycleNumbering",
        "noPageOverflowX",
      ]) {
        if (!metrics[key]) failures.push(`${project.projectId}:${key}`);
      }
      if (protocolRuleAudit.inclusionCount !== project.expectedInclusion) failures.push(`${project.projectId}:inclusionCount`);
      if (protocolRuleAudit.exclusionCount !== project.expectedExclusion) failures.push(`${project.projectId}:exclusionCount`);
      if (protocolRuleAudit.firstInclusionRuleId !== "IN-01") failures.push(`${project.projectId}:firstInclusionRuleId`);
      if (protocolRuleAudit.firstExclusionRuleId !== "EX-01") failures.push(`${project.projectId}:firstExclusionRuleId`);
      if (!String(protocolRuleAudit.inclusionSourceLocator || "").startsWith("docx:paragraph:")) failures.push(`${project.projectId}:inclusionSourceLocator`);
      if (!String(protocolRuleAudit.exclusionSourceLocator || "").startsWith("docx:paragraph:")) failures.push(`${project.projectId}:exclusionSourceLocator`);
      if (!protocolRuleAudit.noPublicPathOrHashLeak) failures.push(`${project.projectId}:publicProtocolRuleLeak`);
      if (metrics.candidateCellOverflowCount) failures.push(`${project.projectId}:candidateCellOverflowCount`);
      if (!metrics.ruleTreeScroll || !["auto", "scroll"].includes(metrics.ruleTreeScroll.overflowY)) failures.push(`${project.projectId}:ruleTreeScrollMode`);
      if (metrics.ruleTreeNodeCount < project.expectedInclusion) failures.push(`${project.projectId}:ruleTreeNodeCount`);
      if (!metrics.subjectTableScroll || metrics.subjectTableScroll.clientHeight > 721) failures.push(`${project.projectId}:subjectTableScrollHeight`);
      if (metrics.subjectRows > 20 && (!metrics.subjectTableScroll || metrics.subjectTableScroll.scrollHeight <= metrics.subjectTableScroll.clientHeight)) {
        failures.push(`${project.projectId}:subjectTableInternalScroll`);
      }
      if (!metrics.subjectsRect || !metrics.reviewRect || !metrics.sideRect || !(metrics.subjectsRect.x < metrics.reviewRect.x && metrics.reviewRect.x < metrics.sideRect.x)) {
        failures.push(`${project.projectId}:desktopThreeColumnOrder`);
      }
    }
    const report = { viewport: { width: 1600, height: 1000 }, results, failures };
    await writeFile(path.join(outputDir, "eligibility_real_projects_qc.json"), JSON.stringify(report, null, 2), "utf8");
    if (failures.length) throw new Error(`Eligibility real-project QC failed: ${failures.join(", ")}`);
    cdp.close();
  } finally {
    chrome.kill("SIGTERM");
    await wait(500);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
