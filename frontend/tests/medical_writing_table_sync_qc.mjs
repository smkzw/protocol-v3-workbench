import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const apiUrl = process.env.API_URL || "http://127.0.0.1:8911";
const outputDir = process.env.QC_OUTPUT_DIR
  || path.resolve(__dirname, "..", "..", "output", "medical-writing-table-sync-qc");
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9475);
const viewport = { width: 1600, height: 1000 };
let apiContractVersion = "";
let apiContractHeader = "X-Workbench-Api-Contract";

const projectCatalog = [
  { projectId: "proj_rux_03_002", projectCode: "RUX-03-002" },
  { projectId: "proj_d001", projectCode: "CMS-D001" },
  { projectId: "proj_my008_pnh_3_01", projectCode: "MY008211A-PNH-3-01" },
];
const requestedProjects = new Set(
  String(process.env.QC_PROJECT_IDS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);
const maxTableSections = Math.max(0, Number(process.env.QC_MAX_TABLE_SECTIONS || 0));
const projects = requestedProjects.size
  ? projectCatalog.filter((project) => requestedProjects.has(project.projectId))
  : projectCatalog;

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const normalized = (value) => String(value || "").replace(/\s+/g, "").toLocaleLowerCase("zh-CN");
const normalizedCellText = (value) => String(value || "")
  .replace(/\r/g, "")
  .split("\n")
  .map((line) => line.replace(/[ \t]+/g, " ").trim())
  .join("\n")
  .replace(/\n{2,}/g, "\n")
  .trim();

async function getJson(url) {
  const headers = url.startsWith(apiUrl) && apiContractVersion
    ? { [apiContractHeader]: apiContractVersion }
    : {};
  const response = await fetch(url, { headers });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForJson(url, timeoutMs = 10000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      return await getJson(url);
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
    await wait(200);
  }
  throw new Error(`Timed out waiting for condition; lastValue=${JSON.stringify(lastValue)}`);
}

async function clickButton(cdp, exactText) {
  const clicked = await evaluate(cdp, `
    (() => {
      const button = Array.from(document.querySelectorAll("button"))
        .find((item) => (item.textContent || "").trim() === ${JSON.stringify(exactText)});
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Button not found: ${exactText}`);
}

async function selectProject(cdp, projectId) {
  const changed = await evaluate(cdp, `
    (() => {
      const select = document.querySelector('select[aria-label="选择临床研究项目"]');
      if (!select) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(
        select,
        ${JSON.stringify(projectId)},
      );
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!changed) throw new Error(`Project switcher not found: ${projectId}`);
  await waitForCondition(
    cdp,
    `document.querySelector('select[aria-label="选择临床研究项目"]')?.value === ${JSON.stringify(projectId)}`,
  );
}

function tableTitle(block, fallback) {
  return String(
    block?.structured_table?.title
      || block?.table_caption?.text
      || block?.title
      || block?.title_hint
      || fallback,
  ).trim();
}

function sourceCaption(block) {
  return String(
    block?.table_caption?.text
      || block?.structured_table?.source_caption?.text
      || "",
  ).trim();
}

function tableNotes(block) {
  return Array.isArray(block?.structured_table?.notes)
    ? block.structured_table.notes.filter((note) => String(note?.text || "").trim())
    : [];
}

function visibleColumnCount(block) {
  return Math.max(
    Number(block?.column_count || 0),
    Number(block?.structured_table?.columns?.length || 0),
    ...(block?.rows || []).map((row) => (row || []).reduce(
      (count, cell) => count + Math.max(1, Number(cell?.column_span || 1)),
      0,
    )),
  );
}

function visibleCells(block) {
  return (block.rows || [])
    .flatMap((row) => row || [])
    .filter((cell) => !cell.hidden)
    .map((cell) => ({ cellId: cell.cell_id, text: String(cell.text || "") }));
}

async function projectTableSections(projectId) {
  const session = await getJson(`${apiUrl}/api/projects/${projectId}/medical-writing/document-session`);
  const sections = [];
  for (let index = 0; index < session.sections.length; index += 1) {
    const summary = session.sections[index];
    const source = await getJson(
      `${apiUrl}/api/projects/${projectId}/medical-writing/document-session/sections/${summary.section_id}`,
    );
    const workingCopy = await getJson(
      `${apiUrl}/api/projects/${projectId}/medical-writing/working-copies/${summary.section_id}`,
    );
    const contentBlocks = Number(workingCopy.revision || 0) >= 1
      ? workingCopy.content_blocks
      : source.content_blocks;
    const tables = contentBlocks.filter((block) => block.block_type === "table");
    if (tables.length) sections.push({ index, summary, tables, workingCopyRevision: workingCopy.revision });
  }
  return { session, sections };
}

async function selectSection(cdp, section) {
  const directoryReady = await evaluate(cdp, `
    (() => {
      if (document.querySelector(".writing-section-buttons > button")) return true;
      const openButton = document.querySelector('button[title="打开研究方案目录"]');
      if (!openButton) return false;
      openButton.click();
      return true;
    })()
  `);
  if (!directoryReady) throw new Error("Research protocol directory control not found");
  await waitForCondition(cdp, `Boolean(document.querySelector(".writing-section-buttons > button"))`, 10000);
  const clicked = await evaluate(cdp, `
    (() => {
      const button = document.querySelectorAll(".writing-section-buttons > button")[${section.index}];
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!clicked) throw new Error(`Section button not found: ${section.summary.section_id}`);
  try {
    await waitForCondition(cdp, `
      (() => {
        const heading = document.querySelector(".rich-editor-meta > strong")?.textContent?.trim();
        return heading === ${JSON.stringify(section.summary.heading)}
          && document.querySelectorAll(".protocol-editor table[data-source-block-id]").length === ${section.tables.length};
      })()
    `, 45000);
  } catch (error) {
    const state = await evaluate(cdp, `({
      requestedIndex: ${section.index},
      requestedSectionId: ${JSON.stringify(section.summary.section_id)},
      requestedHeading: ${JSON.stringify(section.summary.heading)},
      expectedTables: ${section.tables.length},
      activeButtonIndex: Array.from(document.querySelectorAll(".writing-section-buttons > button"))
        .findIndex((button) => button.classList.contains("active")),
      activeButtonText: document.querySelector(".writing-section-buttons > button.active")?.textContent?.trim() || "",
      observedHeading: document.querySelector(".rich-editor-meta > strong")?.textContent?.trim() || "",
      observedTables: document.querySelectorAll(".protocol-editor table[data-source-block-id]").length,
      pickerOptions: document.querySelectorAll('select[aria-label="选择当前表格"] option').length,
      syncBands: document.querySelectorAll(".rich-table-sync-band").length,
      editorHtml: (document.querySelector(".protocol-editor .ProseMirror")?.innerHTML || "").slice(0, 2400),
      structureError: Array.from(document.querySelectorAll(".working-copy-message.danger"))
        .map((item) => item.textContent?.trim() || "")
        .join(" | "),
      workingCopyStatus: document.querySelector(".working-copy-status-bar")?.textContent?.trim() || "",
      message: document.querySelector(".working-copy-message")?.textContent?.trim() || "",
    })`);
    const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
    await writeFile(
      path.join(outputDir, `failure_${section.summary.section_id}.png`),
      Buffer.from(screenshot.data, "base64"),
    );
    throw new Error(`${error.message}; sectionState=${JSON.stringify(state)}`);
  }
  return evaluate(cdp, `
    (() => {
      const saveButton = Array.from(document.querySelectorAll("button"))
        .find((button) => (button.textContent || "").includes("保存工作副本"));
      return {
        saveButtonPresent: Boolean(saveButton),
        saveButtonDisabled: saveButton ? saveButton.disabled : null,
      };
    })()
  `);
}

async function inspectTable(cdp, block, sectionHeading) {
  const title = tableTitle(block, sectionHeading);
  const notes = tableNotes(block).map((note) => String(note.text).trim());
  const source = sourceCaption(block);
  const expectedCells = visibleCells(block);
  const expectedMetric = `${block.rows.length}行×${visibleColumnCount(block)}列`;
  const selected = await evaluate(cdp, `
    (() => {
      const picker = document.querySelector('select[aria-label="选择当前表格"]');
      if (!picker) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(
        picker,
        ${JSON.stringify(block.block_id)},
      );
      picker.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()
  `);
  if (!selected) throw new Error(`Table picker unavailable: ${block.block_id}`);
  try {
    await waitForCondition(cdp, `
      (() => {
        const table = document.querySelector(${JSON.stringify(`.protocol-editor table[data-source-block-id="${block.block_id}"]`)});
        const title = document.querySelector(".rich-table-sync-heading strong")?.textContent?.trim();
        const picker = document.querySelector('select[aria-label="选择当前表格"]');
        const metrics = Array.from(document.querySelectorAll(".rich-table-sync-metrics span"))
          .map((item) => (item.textContent || "").replace(/\\s+/g, ""));
        if (
          !table
          || picker?.value !== ${JSON.stringify(block.block_id)}
          || title !== ${JSON.stringify(title)}
          || !metrics.includes(${JSON.stringify(expectedMetric.replace(/\s+/g, ""))})
          || !metrics.includes(${JSON.stringify(`${notes.length}条附注`)})
        ) return false;
        const tableRect = table.getBoundingClientRect();
        const scrollerRect = document.querySelector(".protocol-editor")?.getBoundingClientRect();
        return Boolean(scrollerRect && tableRect.bottom >= scrollerRect.top && tableRect.top <= scrollerRect.bottom);
      })()
    `, 15000);
  } catch (error) {
    const state = await evaluate(cdp, `({
      expectedBlockId: ${JSON.stringify(block.block_id)},
      expectedTitle: ${JSON.stringify(title)},
      expectedMetric: ${JSON.stringify(expectedMetric)},
      expectedNotes: ${notes.length},
      pickerValue: document.querySelector('select[aria-label="选择当前表格"]')?.value || "",
      title: document.querySelector(".rich-table-sync-heading strong")?.textContent?.trim() || "",
      metrics: Array.from(document.querySelectorAll(".rich-table-sync-metrics span")).map((item) => item.textContent || ""),
      tablePresent: Boolean(document.querySelector(${JSON.stringify(`.protocol-editor table[data-source-block-id="${block.block_id}"]`)})),
      tableRect: (() => {
        const rect = document.querySelector(${JSON.stringify(`.protocol-editor table[data-source-block-id="${block.block_id}"]`)})?.getBoundingClientRect();
        return rect ? { top: rect.top, bottom: rect.bottom, height: rect.height } : null;
      })(),
      scrollerRect: (() => {
        const rect = document.querySelector(".protocol-editor")?.getBoundingClientRect();
        return rect ? { top: rect.top, bottom: rect.bottom, height: rect.height } : null;
      })(),
      scrollerScrollTop: document.querySelector(".protocol-editor")?.scrollTop ?? null,
      proseMirrorScrollTop: document.querySelector(".protocol-editor .ProseMirror")?.scrollTop ?? null,
    })`);
    throw new Error(`${error.message}; tableState=${JSON.stringify(state)}`);
  }
  await wait(80);
  const observed = await evaluate(cdp, `
    (() => {
      const table = document.querySelector(${JSON.stringify(`.protocol-editor table[data-source-block-id="${block.block_id}"]`)});
      const band = document.querySelector(".rich-table-sync-band");
      const scroller = document.querySelector(".protocol-editor");
      const tableRect = table?.getBoundingClientRect();
      const scrollerRect = scroller?.getBoundingClientRect();
      return {
        cells: Array.from(table?.querySelectorAll("th, td") || []).map((cell) => cell.textContent || ""),
        cellDetails: Array.from(table?.querySelectorAll("th, td") || []).map((cell) => ({
          text: cell.innerText || "",
          hardBreakCount: cell.querySelectorAll("br:not(.ProseMirror-trailingBreak)").length,
          paragraphCount: cell.querySelectorAll(":scope > p").length,
        })),
        title: band?.querySelector(".rich-table-sync-heading strong")?.textContent?.trim() || "",
        metrics: Array.from(band?.querySelectorAll(".rich-table-sync-metrics span") || []).map((item) => item.textContent || ""),
        notes: Array.from(band?.querySelectorAll(".rich-table-sync-notes p span") || []).map((item) => item.textContent || ""),
        sourceCaption: band?.querySelector(".rich-table-source-caption strong")?.textContent?.trim() || "",
        horizontalScroll: {
          clientWidth: document.querySelector(".protocol-editor .ProseMirror")?.clientWidth || 0,
          scrollWidth: document.querySelector(".protocol-editor .ProseMirror")?.scrollWidth || 0,
          scrollLeft: document.querySelector(".protocol-editor .ProseMirror")?.scrollLeft || 0,
          controlsPresent: Boolean(band?.querySelector('.rich-table-scroll-controls')),
          leftDisabled: band?.querySelector('button[aria-label="向左浏览表格"]')?.disabled ?? null,
          rightDisabled: band?.querySelector('button[aria-label="向右浏览表格"]')?.disabled ?? null,
        },
        visible: Boolean(scrollerRect && tableRect && tableRect.bottom >= scrollerRect.top && tableRect.top <= scrollerRect.bottom),
        placeholderText: /(表格内容略|未渲染|raw markdown|markdown表格)/i.test(band?.textContent || ""),
        rawMarkdownSeparator: Array.from(table?.querySelectorAll("th, td") || []).some((cell) => /\\|?\s*:?-{3,}:?\s*\\|/.test(cell.textContent || "")),
      };
    })()
  `);
  const failures = [];
  const observedCells = observed.cellDetails.map((cell) => normalizedCellText(cell.text));
  const normalizedExpected = expectedCells.map((cell) => normalizedCellText(cell.text));
  if (JSON.stringify(observedCells) !== JSON.stringify(normalizedExpected)) failures.push("cell_text_or_order");
  const observedLogicalBreaks = observed.cellDetails.map(
    (cell) => Math.max(0, normalizedCellText(cell.text).split("\n").length - 1),
  );
  const expectedLogicalBreaks = expectedCells.map(
    (cell) => Math.max(0, normalizedCellText(cell.text).split("\n").length - 1),
  );
  if (JSON.stringify(observedLogicalBreaks) !== JSON.stringify(expectedLogicalBreaks)) {
    failures.push("cell_logical_line_breaks");
  }
  if (observed.title !== title) failures.push("title");
  if (JSON.stringify(observed.notes.map(normalized)) !== JSON.stringify(notes.map(normalized))) failures.push("notes");
  if (!observed.metrics.map(normalized).includes(normalized(expectedMetric))) failures.push("row_column_metric");
  if (!observed.metrics.map(normalized).includes(normalized(`${notes.length}条附注`))) failures.push("note_metric");
  if (source && normalized(source) !== normalized(title) && normalized(observed.sourceCaption) !== normalized(source)) {
    failures.push("source_caption");
  }
  const horizontalInteraction = {
    required: observed.horizontalScroll.scrollWidth > observed.horizontalScroll.clientWidth + 2,
    before: observed.horizontalScroll.scrollLeft,
    after: observed.horizontalScroll.scrollLeft,
  };
  if (horizontalInteraction.required) {
    if (!observed.horizontalScroll.controlsPresent || observed.horizontalScroll.rightDisabled) {
      failures.push("horizontal_controls");
    } else {
      await evaluate(cdp, `document.querySelector('button[aria-label="向右浏览表格"]')?.click()`);
      await waitForCondition(
        cdp,
        `document.querySelector(".protocol-editor .ProseMirror")?.scrollLeft > ${horizontalInteraction.before + 2}`,
        5000,
      );
      horizontalInteraction.after = await evaluate(
        cdp,
        `document.querySelector(".protocol-editor .ProseMirror")?.scrollLeft || 0`,
      );
      await evaluate(cdp, `document.querySelector(".protocol-editor .ProseMirror")?.scrollTo({ left: 0, behavior: "auto" })`);
      if (horizontalInteraction.after <= horizontalInteraction.before + 2) failures.push("horizontal_control_action");
    }
  }
  if (!observed.visible) failures.push("picker_scroll_linkage");
  if (observed.placeholderText) failures.push("placeholder_text");
  if (observed.rawMarkdownSeparator) failures.push("raw_markdown_separator");
  return {
    blockId: block.block_id,
    tableId: block.table_id,
    title,
    rowCount: block.rows.length,
    columnCount: visibleColumnCount(block),
    visibleCellCount: expectedCells.length,
    noteCount: notes.length,
    observed,
    horizontalInteraction,
    failures,
  };
}

async function verifyDesignerSelectionDoesNotDirty(cdp, blockId) {
  const before = await evaluate(cdp, `
    (() => {
      const saveButton = Array.from(document.querySelectorAll("button"))
        .find((button) => (button.textContent || "").includes("保存工作副本"));
      const openButton = document.querySelector('button[aria-label="全屏编辑当前表格结构与附注"]');
      if (!saveButton || !openButton) return null;
      return { saveDisabled: saveButton.disabled, openDisabled: openButton.disabled };
    })()
  `);
  if (!before || before.openDisabled) {
    return { blockId, skipped: true, reason: "designer_unavailable" };
  }
  if (!before.saveDisabled) {
    return { blockId, skipped: true, reason: "preexisting_dirty_state" };
  }
  await evaluate(
    cdp,
    `document.querySelector('button[aria-label="全屏编辑当前表格结构与附注"]')?.click()`,
  );
  await waitForCondition(cdp, `Boolean(document.querySelector(".structured-table-designer"))`, 10000);
  const selected = await evaluate(cdp, `
    (() => {
      const cellButton = document.querySelector(".std-cell-select-button");
      if (!cellButton) return false;
      cellButton.click();
      return true;
    })()
  `);
  if (!selected) throw new Error(`Designer cell unavailable: ${blockId}`);
  await wait(350);
  const after = await evaluate(cdp, `
    (() => {
      const saveButton = Array.from(document.querySelectorAll("button"))
        .find((button) => (button.textContent || "").includes("保存工作副本"));
      return {
        saveDisabled: saveButton?.disabled ?? null,
        selectedCell: Boolean(document.querySelector("td.selected .std-cell-select-button, th.selected .std-cell-select-button")),
      };
    })()
  `);
  await evaluate(cdp, `document.querySelector('button[aria-label="关闭表格设计器"]')?.click()`);
  await waitForCondition(cdp, `!document.querySelector(".structured-table-designer")`, 10000);
  return {
    blockId,
    skipped: false,
    selectedCell: after.selectedCell,
    saveDisabledAfterSelection: after.saveDisabled,
    failures: [
      ...(!after.selectedCell ? ["designer_cell_selection_missing"] : []),
      ...(after.saveDisabled === false ? ["designer_selection_triggered_dirty_state"] : []),
    ],
  };
}

async function captureProject(cdp, project) {
  await selectProject(cdp, project.projectId);
  await waitForCondition(cdp, `
    (() => {
      const body = (document.body.textContent || "").replace(/[–—−]/g, "-");
      return body.includes(${JSON.stringify(project.projectCode)}) && !body.includes("项目未加载");
    })()
  `);
  await clickButton(cdp, "医学写作");
  await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`, 45000);
  const source = await projectTableSections(project.projectId);
  const sectionResults = [];
  let screenshotCandidate = null;
  const tableSections = maxTableSections ? source.sections.slice(0, maxTableSections) : source.sections;
  for (const section of tableSections) {
    console.log(`[table-sync-qc] ${project.projectId} section ${section.index} ${section.summary.section_id} tables=${section.tables.length}`);
    const loadState = await selectSection(cdp, section);
    const tableResults = [];
    let designerSelectionResult = null;
    for (const block of section.tables) {
      const result = await inspectTable(cdp, block, section.summary.heading);
      tableResults.push(result);
      if (!designerSelectionResult) {
        designerSelectionResult = await verifyDesignerSelectionDoesNotDirty(cdp, block.block_id);
      }
      if (!screenshotCandidate || result.visibleCellCount > screenshotCandidate.visibleCellCount) {
        screenshotCandidate = {
          sectionIndex: section.index,
          sectionId: section.summary.section_id,
          blockId: block.block_id,
          visibleCellCount: result.visibleCellCount,
        };
      }
    }
    sectionResults.push({
      sectionId: section.summary.section_id,
      heading: section.summary.heading,
      workingCopyRevision: section.workingCopyRevision,
      loadState,
      failures: loadState.saveButtonPresent && !loadState.saveButtonDisabled
        ? ["unexpected_dirty_state_on_load"]
        : [
          ...(designerSelectionResult?.failures || []),
        ],
      designerSelectionResult,
      tableResults,
    });
  }
  if (screenshotCandidate) {
    const section = source.sections.find((item) => item.index === screenshotCandidate.sectionIndex);
    await selectSection(cdp, section);
    await inspectTable(
      cdp,
      section.tables.find((block) => block.block_id === screenshotCandidate.blockId),
      section.summary.heading,
    );
  }
  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const screenshotPath = path.join(outputDir, `${project.projectId}_densest_table.png`);
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  const allTables = sectionResults.flatMap((section) => section.tableResults);
  return {
    project,
    sectionCount: source.session.sections.length,
    tableSectionCount: source.sections.length,
    tableCount: allTables.length,
    visibleCellCount: allTables.reduce((sum, table) => sum + table.visibleCellCount, 0),
    noteCount: allTables.reduce((sum, table) => sum + table.noteCount, 0),
    screenshotPath,
    screenshotCandidate,
    sectionResults,
    failures: [
      ...sectionResults.flatMap((section) => (
        section.failures.map((failure) => `${section.sectionId}:${failure}`)
      )),
      ...allTables.flatMap((table) => table.failures.map((failure) => `${table.blockId}:${failure}`)),
    ],
  };
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const runtimeBuild = await getJson(`${appUrl.replace(/\/$/, "")}/runtime-build.json`);
  apiContractVersion = String(runtimeBuild.apiContractVersion || "");
  apiContractHeader = String(runtimeBuild.clientContractHeader || apiContractHeader);
  if (!apiContractVersion) throw new Error("Frontend runtime build does not declare an API contract version");
  const userDataDir = await mkdtemp(path.join(tmpdir(), "medical-writing-table-sync-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });
  let cdp;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const targets = await waitForJson(`http://127.0.0.1:${debugPort}/json/list`);
    const target = targets.find((item) => item.type === "page");
    if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable Google Chrome page target found");
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      ...viewport,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`, 30000);
    const results = [];
    for (const project of projects) results.push(await captureProject(cdp, project));
    const failures = results.flatMap((result) => (
      result.failures.map((failure) => `${result.project.projectId}:${failure}`)
    ));
    const report = {
      generatedAt: new Date().toISOString(),
      viewport,
      appUrl,
      apiUrl,
      scope: "DOM data parity and interaction; not aesthetic acceptance",
      totals: {
        projects: results.length,
        tableSections: results.reduce((sum, result) => sum + result.tableSectionCount, 0),
        tables: results.reduce((sum, result) => sum + result.tableCount, 0),
        visibleCells: results.reduce((sum, result) => sum + result.visibleCellCount, 0),
        notes: results.reduce((sum, result) => sum + result.noteCount, 0),
      },
      results,
      failures,
    };
    await writeFile(path.join(outputDir, "medical_writing_table_sync_qc.json"), JSON.stringify(report, null, 2), "utf8");
    if (failures.length) throw new Error(`Medical writing table sync QC failed: ${failures.join(", ")}`);
  } finally {
    cdp?.close();
    chrome.kill("SIGTERM");
    await wait(500);
    await rm(userDataDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
