#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require("playwright");

async function main() {
  const root = path.resolve(__dirname, "..");
  const htmlPath = process.argv[2] || path.join(root, "docs/medical_monitoring_manual/医学监查子系统说明书.html");
  const source = fs.readFileSync(htmlPath, "utf8");
  if (!source.includes('id="mermaid-lib"')) {
    console.log(JSON.stringify({ htmlPath, diagrams: 0, skipped: true }, null, 2));
    return;
  }

  const browser = await chromium.launch({
    headless: true,
    executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
  await page.waitForFunction(
    () => ["ready", "error"].includes(document.documentElement.dataset.mermaid),
    null,
    { timeout: 120000 },
  );
  const mermaidState = await page.evaluate(() => ({
    state: document.documentElement.dataset.mermaid,
    message: document.documentElement.dataset.mermaidMessage || "",
  }));
  await page.waitForFunction(() => document.documentElement.dataset.interactive === "ready", null, { timeout: 120000 });
  const sourceDiagramCount = await page.locator(".diagram-frame .mermaid").count();
  const renderedDiagramCount = await page.locator(".diagram-frame svg").count();
  const errorFigures = await page.locator(".diagram-frame").evaluateAll((figures) =>
    figures.map((figure, index) => ({
      index: Number(figure.dataset.diagramIndex || index + 1),
      text: (figure.textContent || "").replace(/\s+/g, " ").trim().slice(0, 320),
      ariaRole: figure.querySelector("svg")?.getAttribute("aria-roledescription") || "",
    })).filter((item) =>
      /Syntax error in text|Parse error|mermaid version/i.test(item.text) || /error/i.test(item.ariaRole),
    ),
  );
  if (mermaidState.state !== "ready" || renderedDiagramCount !== sourceDiagramCount || errorFigures.length) {
    const diagramStates = await page.locator(".diagram-frame .mermaid").evaluateAll((elements) =>
      elements.map((element, index) => ({
        index: index + 1,
        processed: element.getAttribute("data-processed"),
        preview: (element.textContent || "").trim().slice(0, 240),
      })),
    );
    await browser.close();
    throw new Error(
      `Mermaid render failed: ${mermaidState.message || "unknown error"}\n` +
      `Error figures: ${JSON.stringify(errorFigures, null, 2)}\n` +
      `${JSON.stringify(diagramStates, null, 2)}`,
    );
  }
  const diagrams = renderedDiagramCount;
  await page.evaluate(() => {
    document.getElementById("mermaid-lib")?.remove();
    document.getElementById("mermaid-init")?.remove();
    document.documentElement.removeAttribute("data-mermaid");
    document.documentElement.removeAttribute("data-mermaid-message");
    document.documentElement.removeAttribute("data-interactive");
    document.querySelectorAll(".mermaid").forEach((element) => element.removeAttribute("data-processed"));
  });
  const output = `<!doctype html>\n${await page.locator("html").evaluate((element) => element.outerHTML)}`;
  await browser.close();
  if (errors.length) {
    throw new Error(`Mermaid browser errors: ${errors.join(" | ")}`);
  }
  if (!diagrams) throw new Error("Mermaid source was present but no SVG was rendered");
  fs.writeFileSync(htmlPath, output);
  console.log(JSON.stringify({
    htmlPath,
    diagrams,
    bytes: Buffer.byteLength(output),
    renderState: mermaidState.state,
    errorFigures,
    warnings: [],
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
