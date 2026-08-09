import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5173/";
const outputDir = process.env.QC_OUTPUT_DIR || path.resolve(__dirname, "..", "..", "records", "visual_qc_20260710");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9374);

const projects = [
  { projectId: "proj_rux_03_002", projectCode: "RUX-03-002", protocolId: "RUX-03-002" },
  { projectId: "proj_d001", projectCode: "CMS-D001", protocolId: "D001-02-002" },
  { projectId: "proj_my008_pnh_3_01", projectCode: "MY008211A-PNH-3-01", protocolId: "MY008211A-PNH-3-01" },
];

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 10000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await json(url);
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
  throw new Error(`Timed out waiting for condition: ${JSON.stringify(lastValue)}`);
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

async function selectProject(cdp, projectId) {
  const selected = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
      setter.call(select, ${JSON.stringify(projectId)});
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!selected) throw new Error(`Project switcher not found: ${projectId}`);
  await waitForCondition(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`);
}

async function captureProject(cdp, project) {
  await selectProject(cdp, project.projectId);
  await waitForCondition(cdp, `
    (() => {
      const bodyText = document.body.textContent || "";
      const normalizedBodyText = bodyText.replace(/[–—−]/g, "-");
      return document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(project.projectId)}
        && !bodyText.includes("项目未加载")
        && !bodyText.includes("未配置当前模块")
        && normalizedBodyText.includes(${JSON.stringify(project.projectCode)});
    })()
  `, 30000);
  await clickButton(cdp, "医学写作");
  try {
    await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`, 30000);
  } catch (error) {
    const state = await evaluate(cdp, `({
      selectedProject: document.querySelector('select[aria-label="选择临床研究项目"]')?.value,
      body: (document.body.textContent || "").slice(0, 2500),
      activeNav: document.querySelector(".nav-item.active")?.textContent || "",
    })`);
    throw new Error(`${error.message}; navigationState=${JSON.stringify(state)}`);
  }

  const session = await json(new URL(`/api/projects/${project.projectId}/medical-writing/document-session`, appUrl));
  const firstSection = session.sections[0];
  const firstSectionBody = await json(
    new URL(`/api/projects/${project.projectId}/medical-writing/document-session/sections/${firstSection.section_id}`, appUrl),
  );
  const firstSourceText = firstSectionBody.content_blocks.find((item) => String(item.text || "").trim())?.text || "";
  let testedSection = firstSection;
  let testedSectionBody = firstSectionBody;
  let testedSectionIndex = 0;
  for (let index = 0; index < Math.min(session.sections.length, 40); index += 1) {
    const candidate = session.sections[index];
    const candidateBody = index === 0
      ? firstSectionBody
      : await json(new URL(`/api/projects/${project.projectId}/medical-writing/document-session/sections/${candidate.section_id}`, appUrl));
    const candidateText = candidateBody.content_blocks
      .map((item) => String(item.text || "").trim())
      .filter(Boolean)
      .join("\n");
    if (candidateText.length >= 20) {
      testedSection = candidate;
      testedSectionBody = candidateBody;
      testedSectionIndex = index;
      break;
    }
  }
  try {
    await waitForCondition(cdp, `
      (() => {
        const editor = document.querySelector(".protocol-editor .ProseMirror");
        const text = editor?.textContent || "";
        return Boolean(editor && text.includes(${JSON.stringify(firstSourceText.slice(0, 60))}));
      })()
    `, 45000);
  } catch (error) {
    const state = await evaluate(cdp, `({
      body: (document.body.textContent || "").slice(0, 4000),
      editorCount: document.querySelectorAll(".protocol-editor .ProseMirror").length,
      sectionButtons: document.querySelectorAll(".writing-section-buttons > button").length,
      blockedText: document.querySelector(".real-document-session-blocked")?.textContent || "",
    })`);
    throw new Error(`${error.message}; browserState=${JSON.stringify(state)}`);
  }

  await clickButton(cdp, "目录");
  await waitForCondition(cdp, `Boolean(document.querySelector('.writing-document-map-drawer[aria-label="研究方案目录"]'))`);
  const sectionButtons = await evaluate(cdp, `document.querySelectorAll(".writing-document-map-drawer .writing-section-buttons > button").length`);
  if (sectionButtons > testedSectionIndex && testedSectionIndex > 0) {
    await evaluate(cdp, `document.querySelectorAll(".writing-document-map-drawer .writing-section-buttons > button")[${testedSectionIndex}].click()`);
    await waitForCondition(cdp, `!document.querySelector('.writing-document-map-drawer[aria-label="研究方案目录"]')`);
    try {
      await waitForCondition(cdp, `
        (() => {
          const editor = document.querySelector(".protocol-editor .ProseMirror");
          const activeHeading = document.querySelector(".writing-section-strip-head strong")?.textContent?.trim() || "";
          return Boolean(
            activeHeading === ${JSON.stringify(testedSection.heading)}
            && editor
            && (editor.textContent || "").trim().length >= 20
          );
        })()
      `, 45000);
    } catch (error) {
      const state = await evaluate(cdp, `({
        activeHeading: document.querySelector(".writing-section-strip-head strong")?.textContent?.trim() || "",
        editorText: (document.querySelector(".protocol-editor .ProseMirror")?.textContent || "").slice(0, 240),
        editorTextLength: (document.querySelector(".protocol-editor .ProseMirror")?.textContent || "").trim().length,
        workingCopyMessage: document.querySelector(".working-copy-message")?.textContent || "",
        blockedText: document.querySelector(".real-document-session-blocked")?.textContent || "",
      })`);
      throw new Error(`${error.message}; testedSection=${JSON.stringify({ index: testedSectionIndex, id: testedSection.section_id, heading: testedSection.heading })}; browserState=${JSON.stringify(state)}`);
    }
    await wait(500);
  } else {
    await evaluate(cdp, `document.querySelector('.writing-document-map-drawer button[title="关闭目录"]')?.click()`);
    await waitForCondition(cdp, `!document.querySelector('.writing-document-map-drawer[aria-label="研究方案目录"]')`);
  }

  const metrics = await evaluate(cdp, `
    (() => {
      const bodyText = document.body.textContent || "";
      const editor = document.querySelector(".protocol-editor .ProseMirror");
      const submitButton = Array.from(document.querySelectorAll("button"))
        .find((item) => (item.textContent || "").includes("提交AI修订"));
      const toolbarButtons = Array.from(document.querySelectorAll(".rich-toolbar button"));
      const allButtons = Array.from(document.querySelectorAll("button"));
      const doc = document.documentElement;
      const body = document.body;
      const editorRect = document.querySelector(".editor-panel")?.getBoundingClientRect();
      const aiRect = document.querySelector(".ai-rail")?.getBoundingClientRect();

      const workingCopyStatus = document.querySelector(".working-copy-status-bar");
      const workingCopyRevisionLabel = document.querySelector(".working-copy-revision")?.textContent?.trim() || "";
      const workingCopyStatusLoaded = Boolean(
        workingCopyStatus && workingCopyRevisionLabel && workingCopyRevisionLabel !== "版本读取中"
      );
      const revisionVisible = /^(版本 \\d+|尚未保存版本)$/.test(workingCopyRevisionLabel);
      const currentRevision = workingCopyRevisionLabel.startsWith("版本 ")
        ? Number(workingCopyRevisionLabel.replace("版本 ", ""))
        : 0;
      const createButton = allButtons.find((item) => (item.textContent || "").includes("创建工作副本"));
      const saveButton = allButtons.find((item) => (item.textContent || "").includes("保存工作副本"));
      const freezeButton = allButtons.find((item) => {
        const label = item.textContent || "";
        return label.includes("确认并冻结") || label.includes("解除冻结");
      });
      const freezeButtonPresent = Boolean(freezeButton);
      const submitAiButtonPresent = Boolean(submitButton);
      const aiCommandBoundaryPresent = toolbarButtons.length >= 5;
      const workingCopyCommandBoundaryCorrect = currentRevision >= 1
        ? Boolean(saveButton && !createButton && freezeButton)
        : Boolean(createButton && !saveButton && freezeButton?.disabled);

      // The current desktop shell keeps the editor and AI rail side by side;
      // the document map is an on-demand overlay and must not compress them.
      const editorLeft = editorRect?.left ?? Infinity;
      const aiLeft = aiRect?.left ?? Infinity;
      const editorAiOrderCorrect = editorLeft < aiLeft;

      // No horizontal page overflow
      const noPageOverflowX = Math.max(doc.scrollWidth, body.scrollWidth) <= window.innerWidth + 1;

      // No local path leak in writing-page outer HTML
      const writingPageHtml = document.querySelector(".writing-page")?.outerHTML || "";
      const lowerWritingPageHtml = writingPageHtml.toLowerCase();
      const noLocalPathLeak = ![
        "/users/",
        "file://",
        "root_path",
        "file_path",
        "absolute_path",
        "allowed_roots",
        "server_path",
      ].some((token) => lowerWritingPageHtml.includes(token));

      return {
        projectId: document.querySelector('select[aria-label="选择临床研究项目"]')?.value,
        hasEditor: Boolean(editor),
        workingCopyEditable: editor?.getAttribute("contenteditable") === "true",
        sourceTextLength: (editor?.textContent || "").trim().length,
        sectionButtonCount: ${sectionButtons},
        revisionFormPresent: Boolean(document.querySelector(".revision-form textarea") && document.querySelector(".revision-form select")),
        revisionSubmitContextGated: Boolean(submitButton && submitButton.disabled),
        toolbarDisabledCount: toolbarButtons.filter((item) => item.disabled).length,
        editorAndAiAligned: Boolean(editorRect && aiRect && Math.abs(editorRect.top - aiRect.top) <= 24),
        noBlockedPlaceholder: !bodyText.includes("真实方案文档会话未就绪") && !bodyText.includes("当前文档会话暂不可用"),
        noDemoFallbackText: !bodyText.includes("不会展示或写入MG-K10演示正文"),
        noLifecycleNumbering: !/第[一二三四五六七八九0-9]+环节|阶段[0-9一二三四五六七八九]/.test(bodyText),
        noLocalPathLeak,
        noPageOverflowX,
        workingCopyStatusLoaded,
        revisionVisible,
        workingCopyCommandBoundaryCorrect,
        freezeButtonPresent,
        submitAiButtonPresent,
        aiCommandBoundaryPresent,
        documentMapHiddenByDefault: !document.querySelector('.writing-document-map-drawer[aria-label="研究方案目录"]'),
        editorAiOrderCorrect,
      };
    })()
  `);

  const screenshot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
  });
  const screenshotPath = path.join(outputDir, `medical_writing_${project.projectId}_desktop.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  return {
    project,
    session: {
      documentId: session.document_id,
      protocolId: session.protocol_id,
      sectionCount: session.sections.length,
      firstSectionId: firstSection.section_id,
      firstSourceLocator: firstSectionBody.content_blocks[0]?.source_locator || "",
      testedSectionId: testedSection.section_id,
      testedSectionHeading: testedSection.heading,
      testedSectionIndex,
    },
    metrics,
    screenshotPath,
  };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-real-qc-"));
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
      width: 1600,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);

    const results = [];
    for (const project of projects) results.push(await captureProject(cdp, project));
    const failures = [];
    for (const result of results) {
      if (result.session.protocolId !== result.project.protocolId) failures.push(`${result.project.projectId}:protocolId`);
      if (result.session.sectionCount < 4) failures.push(`${result.project.projectId}:sectionCount`);
      if (!/^docx:(?:paragraph|table):/.test(result.session.firstSourceLocator)) failures.push(`${result.project.projectId}:sourceLocator`);
      for (const [key, value] of Object.entries(result.metrics)) {
        if (["projectId", "sourceTextLength", "sectionButtonCount", "toolbarDisabledCount"].includes(key)) continue;
        if (!value) failures.push(`${result.project.projectId}:${key}`);
      }
      if (result.metrics.projectId !== result.project.projectId) failures.push(`${result.project.projectId}:projectSwitcher`);
      if (result.metrics.sourceTextLength < 20) failures.push(`${result.project.projectId}:sourceTextLength`);
      if (result.metrics.sectionButtonCount < 4) failures.push(`${result.project.projectId}:sectionButtonCount`);
    }
    const report = { viewport: { width: 1600, height: 1000 }, results, failures };
    await writeFile(path.join(outputDir, "medical_writing_real_projects_qc.json"), JSON.stringify(report, null, 2), "utf8");
    if (failures.length) throw new Error(`Real medical writing QC failed: ${failures.join(", ")}`);
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
