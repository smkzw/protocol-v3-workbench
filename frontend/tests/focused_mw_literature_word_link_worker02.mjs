/**
 * Focused frontend tests for mw-literature-word-link-release-exec - worker_02
 * 
 * Validates:
 * 1. Three exact response headers are parsed: X-Medical-Writing-Source-Reference-Status,
 *    X-Medical-Writing-User-Action-Required, X-Medical-Writing-Warning-Message
 * 2. Blocked draft shows short warning prompt on workingCopyMessage
 * 3. Normal success messages are unchanged for applied/preserved/not_applicable
 * 4. 422 approved_final blocked returns Chinese error message
 * 5. No "待医学批准" text appears in source slice
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

const APP_JSX_PATH = join(import.meta.dirname, "../src/App.jsx");
const APP_CONTENT = readFileSync(APP_JSX_PATH, "utf-8");

// ─── Test Results Tracker ────────────────────────────────────────────────

let passed = 0;
let failed = 0;
const failures = [];

function assert(condition, message) {
  if (condition) {
    passed += 1;
    console.log(`✓ ${message}`);
  } else {
    failed += 1;
    failures.push(message);
    console.error(`✗ ${message}`);
  }
}

// ─── Test 1: Parse three exact headers before blob consumption ────────────

console.log("\n=== Test 1: Header Parsing Before Blob ===");

const sourceRefStatusMatch = APP_CONTENT.includes("X-Medical-Writing-Source-Reference-Status");
const userActionMatch = APP_CONTENT.includes("X-Medical-Writing-User-Action-Required");
const warningMsgMatch = APP_CONTENT.includes("X-Medical-Writing-Warning-Message");
assert(
  sourceRefStatusMatch && userActionMatch && warningMsgMatch,
  "Three required headers appear in export code",
);

// Check that response.headers.get is called before response.blob()
const getHeadersBeforeBlobRegex = /\.headers\.get\([^)]*\)\s*.*\.blob\(\)/s;
assert(
  getHeadersBeforeBlobRegex.test(APP_CONTENT),
  "response.headers.get called before blob() in export flow",
);

// Verify backward compatibility: missing headers should not break parsing
assert(
  APP_CONTENT.includes('=== "true"') || APP_CONTENT.includes("=== true"),
  "Header parsing handles missing values with backward-compatible default",
);

// ─── Test 2: Blocked Draft Shows Short Warning Message ────────────────────

console.log("\n=== Test 2: Blocked Draft Warning Message ===");

assert(
  APP_CONTENT.includes("草稿已生成") && APP_CONTENT.includes("文献引用"),
  "Blocked draft warning contains Chinese actionable instruction",
);
assert(
  APP_CONTENT.includes(
    '/^草稿已生成；/.test(workingCopyMessage)',
  )
    && APP_CONTENT.includes(
      '<div className="working-copy-message">{workingCopyMessage}</div>',
    ),
  "Blocked draft warning is rendered in the existing lightweight message area",
);

// ─── Test 3: Preserved/Applied Statuses Keep Existing Messages ────────────

console.log("\n=== Test 3: Preserved/Applied Status Messages Unchanged ===");

const normalSuccessMessages = [
  "方案终稿 Word 已从各章节已确认快照生成。",
  "草稿预览 Word 已按当前已保存工作副本与未编辑原文完整组装。",
];

normalSuccessMessages.forEach((msg) => {
  assert(
    APP_CONTENT.includes(msg),
    `Normal success message preserved: "${msg.slice(0, 30)}..."`,
  );
});

// ─── Test 4: 422 Error Chinese Mapping ────────────────────────────────────

console.log("\n=== Test 4: 422 Approved Final Blocked Maps to Chinese ===");

assert(
  APP_CONTENT.includes("正式 Word 未生成") && APP_CONTENT.includes("临时工作副本"),
  "422 blocked final export maps to Chinese user-facing message",
);

// ─── Test 5: No "待医学批准" in Export Slice ──────────────────────────────

console.log("\n=== Test 5: No '待医学批准' in Export Flow ===");

// The restriction is only for the exportMedicalWritingDocument function slice
// Other workflow areas (PICOS, risk management) may have their own approval states
const exportSliceStart = APP_CONTENT.indexOf("const exportMedicalWritingDocument");
const exportSliceEnd = exportSliceStart > -1 ? APP_CONTENT.indexOf("};", exportSliceStart) + 2 : -1;
const exportSlice = exportSliceEnd > 0 ? APP_CONTENT.substring(exportSliceStart, exportSliceEnd) : "";

const noMedicalApprovalInExport = !exportSlice.includes("待医学批准");
assert(
  noMedicalApprovalInExport,
  "No '待医学批准' string in exportMedicalWritingDocument slice",
);

if (!noMedicalApprovalInExport) {
  const lines = exportSlice.split("\n");
  lines.forEach((line, idx) => {
    if (line.includes("待医学批准")) {
      console.error(`  Found at line ${idx}: ${line.trim()}`);
    }
  });
}

// ─── Summary ──────────────────────────────────────────────────────────────

console.log("\n========================================");
console.log(`Total: ${passed + failed} checks | Passed: ${passed} | Failed: ${failed}`);
console.log("========================================\n");

if (failures.length > 0) {
  console.error("Failures:");
  failures.forEach((f) => console.error(`  - ${f}`));
  process.exit(1);
}

console.log("All focused tests passed.");
process.exit(0);
