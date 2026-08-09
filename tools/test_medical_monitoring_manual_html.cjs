#!/usr/bin/env node

const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require("playwright");

async function main() {
  const root = path.resolve(__dirname, "..");
  const htmlPath = path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书.html");
  const screenshotPath = path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书_桌面验收.png");
  const coverScreenshotPath = path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书_首页验收.png");
  const tableScreenshotPath = path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书_表格验收.png");
  const diagramScreenshotPath = path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书_图形验收.png");
  const riskDiagramScreenshotPath = path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书_统一风险图验收.png");
  const architectureDiagramScreenshotPath = path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书_架构图验收.png");
  const browser = await chromium.launch({
    headless: true,
    executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
  await page.waitForFunction(() => document.documentElement.dataset.interactive === "ready", null, { timeout: 30000 });

  const initial = await page.evaluate(() => ({
    title: document.title,
    chapters: document.querySelectorAll("article h2").length,
    tocLinks: document.querySelectorAll(".toc-link").length,
    tables: document.querySelectorAll(".table-shell table").length,
    diagrams: document.querySelectorAll(".diagram-frame svg").length,
    nestedTableShells: document.querySelectorAll(".table-shell .table-shell").length,
    diagramErrorFigures: [...document.querySelectorAll(".diagram-frame")].filter((figure) =>
      /Syntax error in text|Parse error|mermaid version/i.test(figure.textContent || "") ||
      /error/i.test(figure.querySelector("svg")?.getAttribute("aria-roledescription") || ""),
    ).length,
    diagramControlsComplete: [...document.querySelectorAll(".diagram-frame")].every((figure) =>
      [".collapse-control", ".zoom-out-control", ".zoom-reset-control", ".zoom-in-control", ".fullscreen-control"]
        .every((selector) => figure.querySelector(selector)),
    ),
    tableControlsComplete: [...document.querySelectorAll(".table-shell")].every((shell) =>
      [".collapse-control", ".density-control", ".fullscreen-control"]
        .every((selector) => shell.querySelector(selector)),
    ),
    linkedSectionReferences: document.querySelectorAll("a.section-reference").length,
    displacedTableHeaders: [...document.querySelectorAll(".table-shell table")].filter((table) => {
      const tableTop = table.getBoundingClientRect().top;
      const headTop = table.tHead?.getBoundingClientRect().top ?? tableTop;
      return Math.abs(headTop - tableTop) > 3;
    }).length,
    logoLoaded: Boolean(document.querySelector(".brand img")?.complete),
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    runtimeMermaidScripts: document.querySelectorAll("#mermaid-lib, #mermaid-init").length,
    defaultDiagramOverflows: [...document.querySelectorAll(".diagram-viewport")].filter((viewport) =>
      viewport.scrollWidth > viewport.clientWidth + 2 || viewport.scrollHeight > viewport.clientHeight + 2,
    ).length,
    defaultDiagramMaxViewportRatio: Math.max(...[...document.querySelectorAll(".diagram-viewport")].map((viewport) =>
      viewport.getBoundingClientRect().height / window.innerHeight,
    )),
    diagramReadabilityFailures: [...document.querySelectorAll(".diagram-frame")].map((figure, index) => {
      const heights = [...figure.querySelectorAll(".nodeLabel, .edgeLabel, text")]
        .map((label) => label.getBoundingClientRect().height)
        .filter((height) => height > 0)
        .sort((a, b) => a - b);
      const lowerQuartile = heights.length ? heights[Math.floor((heights.length - 1) * 0.25)] : 0;
      return { index: index + 1, lowerQuartile };
    }).filter((item) => item.lowerQuartile < 8),
  }));
  await page.locator(".brand img").evaluate(async (image) => {
    if (!image.complete || image.naturalWidth === 0) await image.decode();
  });
  await page.screenshot({ path: coverScreenshotPath, fullPage: false });

  const firstDiagram = page.locator(".diagram-frame").first();
  const firstDiagramViewport = firstDiagram.locator(".diagram-viewport");
  const initialDiagramWidth = await firstDiagram.locator("svg").evaluate((svg) => svg.getBoundingClientRect().width);
  await firstDiagram.locator(".zoom-in-control").click();
  const zoomedDiagramWidth = await firstDiagram.locator("svg").evaluate((svg) => svg.getBoundingClientRect().width);
  await firstDiagram.locator(".zoom-reset-control").click();
  const firstDiagramNode = firstDiagram.locator(".node").first();
  await firstDiagramNode.click();
  const diagramNodeFocused = await firstDiagramNode.evaluate((node) => node.classList.contains("is-focused"));
  await firstDiagram.locator(".zoom-reset-control").click();
  const diagramNodeFocusCleared = await firstDiagramNode.evaluate((node) => !node.classList.contains("is-focused"));
  await firstDiagram.locator(".collapse-control").click();
  const diagramCollapsed = await firstDiagramViewport.isHidden();
  await firstDiagram.locator(".collapse-control").click();
  await firstDiagram.locator(".fullscreen-control").click();
  const diagramFullscreen = await firstDiagram.evaluate((figure) => figure.classList.contains("is-expanded"));
  await page.keyboard.press("Escape");
  const diagramFullscreenClosed = await firstDiagram.evaluate((figure) => !figure.classList.contains("is-expanded"));

  const firstTable = page.locator(".table-shell").first();
  await firstTable.locator(".density-control").click();
  const tableCompact = await firstTable.evaluate((shell) => shell.classList.contains("is-compact"));
  await firstTable.locator(".collapse-control").click();
  const tableCollapsed = await firstTable.locator(".table-viewport").isHidden();
  await firstTable.locator(".collapse-control").click();
  await firstTable.locator(".fullscreen-control").click();
  const tableFullscreen = await firstTable.evaluate((shell) => shell.classList.contains("is-expanded"));
  await page.keyboard.press("Escape");
  const tableFullscreenClosed = await firstTable.evaluate((shell) => !shell.classList.contains("is-expanded"));

  const longTable = page.locator(".table-shell:has(.table-more)").first();
  const hasLongTable = await longTable.count() > 0;
  let longTableExpanded = true;
  if (hasLongTable) {
    await longTable.locator(".table-more").click();
    longTableExpanded = await longTable.evaluate((shell) => !shell.classList.contains("is-preview"));
  }

  const firstSectionReference = page.locator("a.section-reference").first();
  const referenceTarget = await firstSectionReference.getAttribute("href");
  await page.evaluate(() => { document.documentElement.style.scrollBehavior = "auto"; });
  await firstSectionReference.click();
  await page.waitForTimeout(100);
  const referenceTargetVisible = await page.locator(`[id="${referenceTarget.slice(1)}"]`).evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return rect.top >= 0 && rect.top < window.innerHeight;
  });

  await page.locator("#searchInput").fill("剂量调整");
  await page.locator("#searchButton").click();
  const searchMarks = await page.locator("article mark").count();
  await page.evaluate(() => { document.documentElement.style.scrollBehavior = "auto"; });
  await page.locator('.toc-link[href*="subject-timeline"]').first().click();
  await page.waitForTimeout(1200);
  const targetVisible = await page.locator("article h2", { hasText: "Subject Timeline" }).evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return rect.top >= 0 && rect.top < window.innerHeight;
  });
  await page.screenshot({ path: screenshotPath, fullPage: false });

  await page.locator('[id="22-术语使用边界"]').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: tableScreenshotPath, fullPage: false });
  await page.locator('[id="164-禁限用药匹配规则"]').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: diagramScreenshotPath, fullPage: false });
  await page.locator('[id="62-统一医学风险记录"]').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: riskDiagramScreenshotPath, fullPage: false });
  await page.locator('[id="34-系统总体架构"]').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: architectureDiagramScreenshotPath, fullPage: false });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(300);
  const compactDesktop = await page.evaluate(() => ({
    pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    diagramOverflows: [...document.querySelectorAll(".diagram-viewport")].filter((viewport) =>
      viewport.scrollWidth > viewport.clientWidth + 2 || viewport.scrollHeight > viewport.clientHeight + 2,
    ).length,
    maxDiagramViewportRatio: Math.max(...[...document.querySelectorAll(".diagram-viewport")].map((viewport) =>
      viewport.getBoundingClientRect().height / window.innerHeight,
    )),
  }));
  await browser.close();
  const interactionChecks = {
    diagramZoomed: zoomedDiagramWidth > initialDiagramWidth,
    diagramNodeFocused,
    diagramNodeFocusCleared,
    diagramCollapsed,
    diagramFullscreen,
    diagramFullscreenClosed,
    tableCompact,
    tableCollapsed,
    tableFullscreen,
    tableFullscreenClosed,
    hasLongTable,
    longTableExpanded,
    referenceTargetVisible,
  };
  const result = { ...initial, ...interactionChecks, searchMarks, targetVisible, compactDesktop, pageErrors: errors, coverScreenshotPath, screenshotPath, tableScreenshotPath, diagramScreenshotPath, riskDiagramScreenshotPath, architectureDiagramScreenshotPath };
  const ok = initial.chapters >= 30 && initial.tocLinks >= 30 && initial.tables >= 4 && initial.diagrams >= 20 && initial.logoLoaded && !initial.horizontalOverflow && !compactDesktop.pageOverflow && initial.runtimeMermaidScripts === 0 && initial.nestedTableShells === 0 && initial.diagramErrorFigures === 0 && initial.diagramControlsComplete && initial.tableControlsComplete && initial.linkedSectionReferences > 0 && initial.displacedTableHeaders === 0 && initial.defaultDiagramOverflows === 0 && initial.defaultDiagramMaxViewportRatio <= 0.65 && initial.diagramReadabilityFailures.length === 0 && compactDesktop.diagramOverflows === 0 && compactDesktop.maxDiagramViewportRatio <= 0.68 && Object.values(interactionChecks).every(Boolean) && searchMarks > 0 && targetVisible && errors.length === 0;
  console.log(JSON.stringify({ ok, ...result }, null, 2));
  if (!ok) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
