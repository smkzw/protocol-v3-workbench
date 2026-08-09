import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, "..");
const previewPath = path.join(frontendRoot, "src/features/medical-writing/InstrumentAppendixPreview.jsx");
const journeyPath = path.join(frontendRoot, "src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx");
const drawerPath = path.join(frontendRoot, "src/features/medical-writing/AuthoringCompetitorDrawer.jsx");
const panelPath = path.join(frontendRoot, "src/features/writing-reference/WritingReferencePanel.jsx");
const stylesPath = path.join(frontendRoot, "src/styles.css");

function orderInstrumentAppendixPages(pages = []) {
  return [...(pages || [])]
    .filter((block) => block && block.block_type === "appendix_image")
    .sort((left, right) => {
      const leftPage = Number(left.page_number) || 0;
      const rightPage = Number(right.page_number) || 0;
      if (leftPage !== rightPage) return leftPage - rightPage;
      return String(left.block_id || "").localeCompare(String(right.block_id || ""));
    });
}

function makePage(pageNumber, { pageCount = 9, instrumentId = "ibdq", base64 = null } = {}) {
  return {
    block_id: `mwgenerated_appendix_${instrumentId}_${String(pageNumber).padStart(3, "0")}`,
    block_type: "appendix_image",
    attachment_kind: "assessment_instrument_page",
    instrument_id: instrumentId,
    page_number: pageNumber,
    page_count: pageCount,
    media_type: "image/png",
    image_base64: base64 ?? `page-${pageNumber}-payload`,
    render_dpi: 220,
  };
}

const failures = [];
function check(name, condition, detail = "") {
  if (!condition) failures.push(detail ? `${name}: ${detail}` : name);
}

const [previewSource, journeySource, drawerSource, panelSource, stylesSource] = await Promise.all([
  readFile(previewPath, "utf8"),
  readFile(journeyPath, "utf8"),
  readFile(drawerPath, "utf8"),
  readFile(panelPath, "utf8"),
  readFile(stylesPath, "utf8"),
]);

// --- 9 real-shape appendix blocks → ordered thumbnails ---
const shuffled = [7, 1, 9, 3, 5, 2, 8, 4, 6].map((n) => makePage(n, { pageCount: 12 }));
const ordered = orderInstrumentAppendixPages(shuffled);
check("nine-pages-count", ordered.length === 9, `got ${ordered.length}`);
check(
  "nine-pages-order",
  ordered.map((item) => item.page_number).join(",") === "1,2,3,4,5,6,7,8,9",
  ordered.map((item) => item.page_number).join(","),
);
check(
  "nine-pages-no-base64-copy-in-order-fn",
  ordered.every((item, index) => item === shuffled.find((page) => page.page_number === index + 1)),
  "ordered pages should retain original object references",
);

// --- mismatch and zero-page truthfulness ---
const mismatchDeclared = ordered[0]?.page_count;
check("mismatch-declared-vs-actual", mismatchDeclared === 12 && ordered.length === 9);
check("zero-page-order", orderInstrumentAppendixPages([]).length === 0);
check("zero-page-empty-message-path", previewSource.includes('data-page-count="0"') && previewSource.includes("emptyMessage"));
check("mismatch-notice", previewSource.includes("appendix-page-count-mismatch") && previewSource.includes("不阻断核对"));

// --- enlarged review: single current image, no base64 state duplication ---
check("lazy-thumbnails", previewSource.includes('loading="lazy"'));
check("review-image-testid", previewSource.includes('data-testid="instrument-appendix-review-image"'));
check("review-index-state-only", /useState\(null\)/.test(previewSource) && !/useState\([^\)]*image_base64/.test(previewSource));
check("no-localStorage-base64", !/localStorage[\s\S]{0,80}image_base64|image_base64[\s\S]{0,80}localStorage/.test(previewSource));
check("escape-close", previewSource.includes('event.key === "Escape"'));
check("arrow-nav", previewSource.includes('ArrowLeft') && previewSource.includes('ArrowRight'));
check("prev-next-actions", previewSource.includes('data-action="appendix-prev"') && previewSource.includes('data-action="appendix-next"'));
check("page-indicator", previewSource.includes('data-testid="appendix-page-indicator"'));
check("page-selector", previewSource.includes('data-testid="appendix-page-selector"'));
check("only-current-full-image-comment", previewSource.includes("Only the current full-page image is mounted"));

// --- journey wires real working-copy blocks, preserves upload/readonly ---
check("journey-imports-preview", journeySource.includes('from "./InstrumentAppendixPreview"'));
check("journey-filters-appendix-image", journeySource.includes('block.block_type === "appendix_image"') && journeySource.includes('attachment_kind === "assessment_instrument_page"'));
check("journey-keeps-block-refs", journeySource.includes("Keep block references only") || journeySource.includes("setAppendixPages(pages)"));
check("journey-readonly-review", journeySource.includes("只读模式可审阅原始页面，不可上传或删除附件"));
check("journey-upload-when-not-readonly", journeySource.includes("!readOnly && <div className=\"authoring-instrument-appendix-actions\""));

// --- W4-A composite adoption remains wired alongside the appendix surface ---
check("composite-panel-preserved", journeySource.includes("AuthoringCandidatePackagePanel"));
check("composite-endpoint-preserved", journeySource.includes("prefill-package/adopt-composite"));
check("legacy-low-risk-batch-removed", !journeySource.includes("adoptLowRiskPrefills") && !journeySource.includes("LOW_RISK_BATCH_PREFILL_FIELDS"));

// --- drawer early open, keep-mounted, draft isolation ---
check("drawer-file", drawerSource.includes("WritingReferencePanel") && drawerSource.includes("embedded") && drawerSource.includes("compact"));
check("drawer-keep-mounted", drawerSource.includes("keepPanelMounted") && drawerSource.includes("shouldRenderPanel"));
check("drawer-escape", drawerSource.includes('Escape'));
check("drawer-close-a11y", drawerSource.includes('aria-label="关闭竞品处理抽屉"') && drawerSource.includes("title="));
check("journey-open-from-early-step", journeySource.includes('data-testid="open-competitor-drawer"') && journeySource.includes("authoring-competitor-toolbar"));
check("journey-drawer-keep-mounted-prop", journeySource.includes("keepPanelMounted"));
check("close-does-not-reset-framing", !/setCompetitorDrawerOpen\(false\)[\s\S]{0,120}setFraming\(/.test(journeySource));
check("panel-embedded-optional", panelSource.includes("embedded = false") && panelSource.includes("compact = false"));
check("panel-default-header-preserved", panelSource.includes("{!embedded && (") && panelSource.includes("建稿前语料准备"));
check("panel-snapshot-collapsed-when-embedded", panelSource.includes("writing-reference-snapshot-details"));
check("styles-drawer-width", stylesSource.includes("authoring-competitor-drawer") && stylesSource.includes("560px") && stylesSource.includes("480px"));
check("styles-visibility-keep-alive", stylesSource.includes("visibility: hidden") && stylesSource.includes("translateX(100%)"));

const report = {
  passed: failures.length === 0,
  checks: {
    ninePageOrder: ordered.map((item) => item.page_number),
    mismatchDeclaredVsActual: { declared: mismatchDeclared, actual: ordered.length },
    zeroPages: orderInstrumentAppendixPages([]).length,
  },
  failures,
  sources: {
    previewPath,
    journeyPath,
    drawerPath,
    panelPath,
  },
};

console.log(JSON.stringify(report, null, 2));
if (failures.length) {
  process.exitCode = 1;
  throw new Error(`medical_writing_appendix_preview_qc failed: ${failures.join("; ")}`);
}
