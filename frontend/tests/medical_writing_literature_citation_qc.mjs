import { spawn, spawnSync } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const debugPort = Number(process.env.CHROME_DEBUG_PORT || 9512);
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const outputDir = process.env.QC_OUTPUT_DIR
  || "records/active_slices/medical_writing_editor_references_20260715/browser_qc";
const projectId = process.env.QC_PROJECT_ID || "proj_rux_03_002";
const sectionId = process.env.QC_SECTION_ID
  || "mwsec_proj_rux_03_002_8783a740fc05_c848ed4d86b7";
const targetBlockId = process.env.QC_TARGET_BLOCK_ID
  || "mwblock_mwsec_proj_rux_03_002_8783a740fc05_c848ed4d86b7_bf5c2fa8e722";
const doi = process.env.QC_DOI || "10.1016/j.jaad.2021.04.085";
const expectedTitleTerms = (process.env.QC_EXPECTED_TITLE_TERMS || "ruxolitinib|atopic dermatitis")
  .split("|")
  .map((value) => value.trim())
  .filter(Boolean);
const primaryTitleTerm = expectedTitleTerms[0] || "";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function decodeXmlText(value) {
  return String(value || "")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'")
    .replaceAll("&amp;", "&");
}

function wordText(xml) {
  return Array.from(String(xml || "").matchAll(/<w:t(?:\s[^>]*)?>([\s\S]*?)<\/w:t>/g))
    .map((match) => decodeXmlText(match[1]))
    .join("");
}

function normalizedText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function inspectUnifiedCitationDocx(docxPath, targetBlock) {
  const extracted = spawnSync("unzip", ["-p", docxPath, "word/document.xml"], {
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  if (extracted.status !== 0 || !extracted.stdout) {
    throw new Error(`Could not inspect exported DOCX XML: ${extracted.stderr || extracted.status}`);
  }
  const paragraphs = Array.from(extracted.stdout.matchAll(/<w:p(?:\s[^>]*)?>[\s\S]*?<\/w:p>/g))
    .map((match) => ({ xml: match[0], text: normalizedText(wordText(match[0])) }));
  const targetText = normalizedText(String(targetBlock?.text || "").replace(/\[待编号\]\s*$/, ""));
  const targetExcerpt = targetText.slice(0, 120);
  const bodyParagraph = paragraphs.find((paragraph) => (
    targetExcerpt
    && paragraph.text.includes(targetExcerpt)
    && /<w:hyperlink\b/.test(paragraph.xml)
  ));
  if (!bodyParagraph) throw new Error("Exported DOCX does not contain the cited target paragraph");
  const hyperlinks = Array.from(bodyParagraph.xml.matchAll(/<w:hyperlink\b([^>]*)>([\s\S]*?)<\/w:hyperlink>/g))
    .map((match) => ({
      anchor: match[1].match(/w:anchor="([^"]+)"/)?.[1] || "",
      text: wordText(match[2]),
    }))
    .filter((item) => /^\[\d+(?:,\d+)*\]$/.test(item.text) && item.anchor);
  const citation = hyperlinks.at(-1);
  if (!citation) throw new Error("Exported target paragraph does not contain a numbered citation hyperlink");
  const referenceParagraph = paragraphs.find((paragraph) => (
    paragraph.xml.includes(`w:name="${citation.anchor}"`)
  ));
  if (!referenceParagraph || !referenceParagraph.text.startsWith(`${citation.text} `)) {
    throw new Error(`DOCX citation ${citation.text} does not resolve to a matching numbered reference entry`);
  }
  return {
    verified: true,
    citationText: citation.text,
    bookmarkAnchor: citation.anchor,
    referenceEntryText: referenceParagraph.text,
  };
}

async function request(relative, options = {}) {
  const response = await fetch(new URL(relative, appUrl), options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("json")
    ? await response.json().catch(() => ({}))
    : await response.arrayBuffer();
  if (!response.ok) throw new Error(`${response.status}: ${relative}\n${JSON.stringify(payload)}`);
  return payload;
}

async function waitForJson(url, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      return await (await fetch(url)).json();
    } catch {
      await wait(200);
    }
  }
  throw new Error(`Timed out waiting for ${url}`);
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
    const callback = pending.get(message.id);
    if (!callback) return;
    pending.delete(message.id);
    clearTimeout(callback.timer);
    if (message.error) callback.reject(new Error(message.error.message));
    else callback.resolve(message.result || {});
  });
  return {
    ready,
    send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`CDP command timed out: ${method}`));
        }, 15000);
        pending.set(id, { resolve, reject, timer });
        ws.send(JSON.stringify({ id, method, params }));
      });
    },
    close: () => ws.close(),
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
}

async function waitForCondition(cdp, expression, timeoutMs = 45000) {
  const started = Date.now();
  let last;
  while (Date.now() - started < timeoutMs) {
    last = await evaluate(cdp, expression);
    if (last) return last;
    await wait(200);
  }
  throw new Error(`Timed out: ${expression}; last=${JSON.stringify(last)}`);
}

async function clickMatching(cdp, selector, label) {
  const clicked = await evaluate(cdp, `(() => {
    const node = Array.from(document.querySelectorAll(${JSON.stringify(selector)}))
      .find((candidate) => (candidate.textContent || "").includes(${JSON.stringify(label)}) && !candidate.disabled);
    if (!node) return false;
    node.scrollIntoView({ block: "center", inline: "nearest" });
    node.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Enabled control not found: ${selector}/${label}`);
}

async function setProject(cdp) {
  const changed = await evaluate(cdp, `(() => {
    const control = document.querySelector('select[aria-label="选择临床研究项目"]');
    if (!control || control.disabled) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(control, ${JSON.stringify(projectId)});
    control.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error("Project selector unavailable");
}

function citationReferenceIds(value, found = []) {
  if (!value || typeof value !== "object") return found;
  for (const mark of value.marks || []) {
    if (mark?.type !== "citation") continue;
    if (mark.attrs?.referenceId) found.push(mark.attrs.referenceId);
    for (const referenceId of mark.attrs?.referenceIds || []) {
      if (referenceId) found.push(referenceId);
    }
  }
  for (const child of value.content || []) citationReferenceIds(child, found);
  return found;
}

async function ensureEditableCopy() {
  const copy = await request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`);
  if (copy.revision >= 1) return copy;
  return request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      document_id: copy.document_id,
      expected_revision: copy.revision,
      content_blocks: copy.content_blocks,
      actor: "codex_literature_citation_qc",
      idempotency_key: "literature-citation-qc-seed-v1",
    }),
  });
}

async function restoreCopy(baseline) {
  const current = await request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`);
  if (JSON.stringify(current.content_blocks) === JSON.stringify(baseline.content_blocks)) return current;
  return request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      document_id: baseline.document_id,
      expected_revision: current.revision,
      content_blocks: baseline.content_blocks,
      actor: "codex_literature_citation_qc_restore",
      idempotency_key: `literature-citation-qc-restore-r${current.revision}`,
    }),
  });
}

async function ensureReference() {
  const existing = await request(`/api/projects/${projectId}/medical-writing/literature`);
  const match = existing.references.find((item) => item.doi === doi);
  if (match) return match;
  const imported = await request(`/api/projects/${projectId}/medical-writing/literature/imports`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      source_input: doi,
      override_validation: false,
      override_reason: "",
      actor: "medical_manager_qc",
      idempotency_key: `literature-citation-qc-${projectId}-${doi}`,
    }),
  });
  return imported.reference;
}

async function main() {
  if (process.env.QC_ISOLATED_RUNTIME !== "1") {
    throw new Error(
      "Refusing to mutate a shared project runtime. Run through the isolated citation QC harness.",
    );
  }
  await mkdir(outputDir, { recursive: true });
  const reference = await ensureReference();
  const missingTitleTerms = expectedTitleTerms.filter((term) => (
    !reference.title.toLocaleLowerCase().includes(term.toLocaleLowerCase())
  ));
  if (missingTitleTerms.length) {
    throw new Error(
      `Resolved DOI does not match ${projectId}; missing title terms ${missingTitleTerms.join(", ")}: ${reference.title}`,
    );
  }
  const baseline = await ensureEditableCopy();
  const session = await request(`/api/projects/${projectId}/medical-writing/document-session`);
  const sectionIndex = session.sections.findIndex((item) => item.section_id === sectionId);
  if (sectionIndex < 0) throw new Error("Target section unavailable");

  const userDataDir = await mkdtemp(path.join(tmpdir(), "mw-literature-qc-"));
  const chrome = spawn(chromePath, [
    "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
    `--remote-debugging-port=${debugPort}`, `--user-data-dir=${userDataDir}`, "about:blank",
  ], { stdio: "ignore" });
  let cdp;
  let result;
  try {
    await waitForJson(`http://127.0.0.1:${debugPort}/json/version`);
    const target = await (await fetch(`http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(appUrl)}`, { method: "PUT" })).json();
    cdp = createCdp(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await waitForCondition(cdp, `(() => {
      const control = document.querySelector('select[aria-label="选择临床研究项目"]');
      return Boolean(control && !control.disabled && Array.from(control.options).some((option) => option.value === ${JSON.stringify(projectId)}));
    })()`);
    await setProject(cdp);
    await clickMatching(cdp, ".nav-item", "医学写作");
    await waitForCondition(cdp, `document.body.textContent.includes("研究方案文档编辑与AI修订")`);
    await clickMatching(cdp, ".writing-title-actions button", "目录");
    await waitForCondition(cdp, `document.querySelectorAll(".writing-section-buttons > button").length > ${sectionIndex}`);
    await evaluate(cdp, `document.querySelectorAll(".writing-section-buttons > button")[${sectionIndex}].click()`);
    await waitForCondition(cdp, `Boolean(document.querySelector(${JSON.stringify(`[data-source-block-id="${targetBlockId}"]`)}))`);

    const cursorSet = await evaluate(cdp, `(() => {
      const wrapper = document.querySelector(${JSON.stringify(`[data-source-block-id="${targetBlockId}"]`)});
      const paragraph = wrapper?.querySelector("p, h1, h2, h3, h4, h5, h6");
      const proseMirror = wrapper?.closest(".ProseMirror");
      if (!paragraph || !proseMirror) return false;
      proseMirror.focus();
      const range = document.createRange();
      range.selectNodeContents(paragraph);
      range.collapse(false);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      document.dispatchEvent(new Event("selectionchange", { bubbles: true }));
      return true;
    })()`);
    if (!cursorSet) throw new Error("Could not place the editor cursor");
    await clickMatching(cdp, ".rail-tabs button", "文献");
    await waitForCondition(
      cdp,
      `document.querySelector(".medical-literature-list")?.textContent.toLocaleLowerCase().includes(${JSON.stringify(primaryTitleTerm.toLocaleLowerCase())})`,
    );
    const inserted = await evaluate(cdp, `(() => {
      const card = Array.from(document.querySelectorAll(".medical-literature-list article"))
        .find((node) => (node.textContent || "").toLocaleLowerCase().includes(${JSON.stringify(primaryTitleTerm.toLocaleLowerCase())}));
      const button = Array.from(card?.querySelectorAll("button") || [])
        .find((node) => (node.textContent || "").includes("插入引文") && !node.disabled);
      if (!button) return false;
      button.click();
      return true;
    })()`);
    if (!inserted) throw new Error("Citable literature card not found");
    await waitForCondition(cdp, `document.querySelector('.protocol-citation[data-reference-ids*="${reference.reference_id}"]')?.textContent === "[待编号]"`);
    await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("有未保存修订")`);
    const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
    await writeFile(
      path.join(outputDir, `medical_writing_literature_citation_${projectId}.png`),
      Buffer.from(screenshot.data, "base64"),
    );
    await clickMatching(cdp, ".working-copy-actions button", "保存工作副本");
    await waitForCondition(cdp, `document.querySelector(".working-copy-status-main")?.textContent.includes("已保存")`);

    const saved = await request(`/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`);
    const targetBlock = saved.content_blocks.find((block) => block.block_id === targetBlockId);
    const savedReferenceIds = citationReferenceIds(targetBlock?.rich_text);
    const docx = await request(`/api/projects/${projectId}/medical-writing/document.docx?mode=draft_preview`);
    const docxPath = path.join(
      outputDir,
      `medical_writing_literature_citation_${projectId}_r${saved.revision}.docx`,
    );
    await writeFile(docxPath, Buffer.from(docx));
    const referenceIdPersisted = savedReferenceIds.includes(reference.reference_id);
    const docxGenerated = docx.byteLength > 10000;
    const docxUnifiedIndex = inspectUnifiedCitationDocx(docxPath, targetBlock);
    result = {
      passed: referenceIdPersisted && docxGenerated && docxUnifiedIndex.verified,
      scope: "frontend_reference_identity_and_exporter_unified_index",
      projectId,
      sectionId,
      targetBlockId,
      referenceId: reference.reference_id,
      doi: reference.doi,
      title: reference.title,
      baselineRevision: baseline.revision,
      savedRevision: saved.revision,
      savedReferenceIds,
      referenceIdPersisted,
      docxBytes: docx.byteLength,
      docxGenerated,
      docxUnifiedIndex,
    };
    if (!result.passed) throw new Error(`Citation workflow failed: ${JSON.stringify(result)}`);
  } finally {
    const restored = await restoreCopy(baseline);
    if (result) result.restoredRevision = restored.revision;
    cdp?.close();
    const chromeExited = new Promise((resolve) => chrome.once("exit", resolve));
    chrome.kill("SIGTERM");
    await Promise.race([chromeExited, wait(5000)]);
    if (chrome.exitCode === null) {
      chrome.kill("SIGKILL");
      await Promise.race([chromeExited, wait(2000)]);
    }
    await rm(userDataDir, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 200,
    });
  }
  await writeFile(
    path.join(outputDir, `medical_writing_literature_citation_${projectId}_qc.json`),
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
