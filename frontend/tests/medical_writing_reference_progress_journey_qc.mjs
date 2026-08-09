/**
 * Focused tests for medical writing reference progress journey logic.
 * Tests: status mapping, stage sequence, active stage computation,
 * next-action labels, legacy fallback, retry/completion scenarios,
 * no developer-log text leakage.
 */
import { strict as assert } from "node:assert";
import {
  STAGE_SEQUENCE,
  normalizeStage,
  getStageLabel,
  getActiveStages,
  getNextAction,
  isBusyStage,
} from "../src/features/writing-reference/progressJourneyLogic.mjs";

let passed = 0;
let failed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (error) {
    failed += 1;
    failures.push({ name, message: error.message });
  }
}

// 1. Stage sequence is well-defined
test("STAGE_SEQUENCE contains all expected stages in order", () => {
  assert.ok(STAGE_SEQUENCE.length >= 12, "Must have at least 12 stages");
  assert.ok(STAGE_SEQUENCE.includes("ocr_running"), "Must include ocr_running");
  assert.ok(STAGE_SEQUENCE.includes("toc_planning"), "Must include toc_planning");
  assert.ok(STAGE_SEQUENCE.includes("translating_hy_mt2"), "Must include translating_hy_mt2");
  assert.ok(STAGE_SEQUENCE.includes("integration_qc"), "Must include integration_qc");
  assert.ok(STAGE_SEQUENCE.includes("candidate_ready"), "Must include candidate_ready");
  const ocrIdx = STAGE_SEQUENCE.indexOf("ocr_running");
  const parseIdx = STAGE_SEQUENCE.indexOf("parsing");
  const candidateIdx = STAGE_SEQUENCE.indexOf("candidate_ready");
  assert.ok(ocrIdx > parseIdx, "OCR must come after parsing");
  assert.ok(candidateIdx > ocrIdx, "candidate_ready must come after OCR");
});

// 2. Backward-compatible status mapping
test("normalizeStage maps legacy pending/running/completed", () => {
  assert.equal(normalizeStage("pending"), "waiting");
  assert.equal(normalizeStage("accepted"), "downloading");
  assert.equal(normalizeStage("running"), "parsing");
  assert.equal(normalizeStage("succeeded"), "candidate_ready");
  assert.equal(normalizeStage("completed"), "candidate_ready");
});

test("normalizeStage maps legacy failure statuses", () => {
  assert.equal(normalizeStage("failed"), "failed_retryable");
  assert.equal(normalizeStage("failed_retryable"), "failed_retryable");
  assert.equal(normalizeStage("failed_terminal"), "failed_terminal");
});

test("normalizeStage maps legacy review statuses", () => {
  assert.equal(normalizeStage("review_required"), "medical_review");
  assert.equal(normalizeStage("needs_review"), "medical_review");
  assert.equal(normalizeStage("mismatch"), "fidelity_blocked");
});

test("normalizeStage maps new additive statuses correctly", () => {
  assert.equal(normalizeStage("extracting"), "extracting");
  assert.equal(normalizeStage("ocr_running"), "ocr_running");
  assert.equal(normalizeStage("toc_planning"), "toc_planning");
  assert.equal(normalizeStage("translating_hy_mt2"), "translating_hy_mt2");
  assert.equal(normalizeStage("integration_qc"), "integration_qc");
  assert.equal(normalizeStage("candidate_ready"), "candidate_ready");
  assert.equal(normalizeStage("fidelity_blocked"), "fidelity_blocked");
  assert.equal(normalizeStage("excluded"), "excluded");
});

test("normalizeStage handles empty/unknown with fallback", () => {
  assert.equal(normalizeStage(""), "waiting");
  assert.equal(normalizeStage(null), "waiting");
  assert.equal(normalizeStage(undefined), "waiting");
  assert.equal(normalizeStage("something_unknown"), "unknown");
});

// 3. Stage labels are human-readable
test("getStageLabel returns Chinese labels for all known stages", () => {
  assert.equal(getStageLabel("ocr_running"), "OCR识别中");
  assert.equal(getStageLabel("toc_planning"), "目录识别中");
  assert.equal(getStageLabel("translating_hy_mt2"), "Hy-MT2翻译中");
  assert.equal(getStageLabel("integration_qc"), "衔接核对中");
  assert.equal(getStageLabel("candidate_ready"), "候选已就绪");
  assert.equal(getStageLabel("failed_retryable"), "失败（可重试）");
  assert.equal(getStageLabel("failed_terminal"), "失败（终止）");
  assert.equal(getStageLabel("excluded"), "规划后排除");
});

test("getStageLabel fallback for unknown stage", () => {
  const label = getStageLabel("unknown_stage");
  assert.equal(label, "处理中");
});

// 4. Active stages computed correctly
test("getActiveStages counts items per stage", () => {
  const items = [
    { status: "pending" },
    { status: "running" },
    { status: "running" },
    { status: "completed" },
  ];
  const counts = getActiveStages(items);
  assert.equal(counts.get("waiting"), 1);
  assert.equal(counts.get("parsing"), 2);
  assert.equal(counts.get("candidate_ready"), 1);
});

test("getActiveStages handles empty items", () => {
  const counts = getActiveStages([]);
  assert.equal(counts.size, 0);
});

test("getActiveStages handles generation_status field", () => {
  const items = [
    { generation_status: "ocr_running" },
    { generation_status: "translating_hy_mt2" },
  ];
  const counts = getActiveStages(items);
  assert.equal(counts.get("ocr_running"), 1);
  assert.equal(counts.get("translating_hy_mt2"), 1);
});

// 5. Next action labels
test("getNextAction provides actionable labels", () => {
  assert.equal(getNextAction({ status: "candidate_ready" }), "可进入下一步");
  assert.equal(getNextAction({ status: "failed" }), "可重试失败项");
  assert.equal(getNextAction({ status: "fidelity_blocked" }), "需核对原文");
  assert.equal(getNextAction({ status: "medical_review" }), "等待医学审核");
  assert.equal(getNextAction({ status: "ocr_running" }), "等待OCR识别完成");
  assert.equal(getNextAction({ status: "excluded" }), "不在所选章节范围，无需生成");
});

// 6. Empty state handling
test("Empty items produce empty active stages", () => {
  const counts = getActiveStages([]);
  assert.equal(counts.size, 0);
  const action = getNextAction({ status: "" });
  assert.equal(action, "等待启动");
});

// 7. No developer-log text in labels
test("Stage labels contain no developer-log text", () => {
  const forbiddenTokens = ["debug", "trace", "console", "stack", "error:", "warn:", "payload", "raw", "internal"];
  const allStages = [...STAGE_SEQUENCE, "failed_retryable", "failed_terminal", "fidelity_blocked", "excluded", "skipped"];
  for (const stage of allStages) {
    const label = getStageLabel(stage);
    const lower = label.toLowerCase();
    for (const token of forbiddenTokens) {
      assert.ok(!lower.includes(token), `Label for ${stage} must not contain developer-log text: ${token}`);
    }
  }
});

// 8. Completion summary
test("All-ready items map to candidate_ready stage", () => {
  const items = [
    { status: "completed" },
    { status: "succeeded" },
    { status: "prepared" },
  ];
  const counts = getActiveStages(items);
  assert.equal(counts.get("candidate_ready"), 2);
  assert.equal(counts.get("prepared"), 1);
});

test("Prepared source material remains distinct from generated candidates", () => {
  assert.equal(normalizeStage("prepared"), "prepared");
  assert.equal(getStageLabel("prepared"), "资料已准备");
  assert.equal(isBusyStage("prepared"), false);
  assert.equal(isBusyStage("excluded"), false);
});

// 9. Mixed states
test("Mixed states produce correct counts per stage", () => {
  const items = [
    { status: "completed" },
    { status: "failed" },
    { status: "failed_retryable" },
    { status: "fidelity_blocked" },
  ];
  const counts = getActiveStages(items);
  assert.equal(counts.get("candidate_ready"), 1);
  assert.equal(counts.get("failed_retryable"), 2); // "failed" + "failed_retryable"
  assert.equal(counts.get("fidelity_blocked"), 1);
});

// 10. Unknown contract states must not pretend that a search is running
test("Unknown status falls back gracefully", () => {
  const label = getStageLabel(normalizeStage("totally_unknown"));
  assert.equal(label, "状态待同步");
});

// 11. Retry scenario
test("Failed_retryable items show retryable next action", () => {
  const action = getNextAction({ status: "failed_retryable" });
  assert.equal(action, "可重试失败项");
});

test("Failed_terminal items show manual handling needed", () => {
  const action = getNextAction({ status: "failed_terminal" });
  assert.equal(action, "需人工处理");
});

// 12. Progression order integrity
test("Stage sequence has no duplicates", () => {
  const unique = new Set(STAGE_SEQUENCE);
  assert.equal(unique.size, STAGE_SEQUENCE.length, "Stage sequence must not have duplicates");
});

test("Stage sequence is monotonically ordered", () => {
  const expectedOrder = [
    "searching", "screening", "downloading", "parsing", "extracting",
    "ocr_running", "validating", "prepared", "toc_planning",
    "translating_hy_mt2", "integration_qc", "medical_review",
    "corpus_admission", "chapter_mapping", "candidate_ready",
  ];
  for (let i = 0; i < expectedOrder.length; i += 1) {
    assert.equal(STAGE_SEQUENCE[i], expectedOrder[i], `Stage at index ${i} must be ${expectedOrder[i]}`);
  }
});

// 13. Case insensitivity
test("normalizeStage is case-insensitive", () => {
  assert.equal(normalizeStage("PENDING"), "waiting");
  assert.equal(normalizeStage("Running"), "parsing");
  assert.equal(normalizeStage("COMPLETED"), "candidate_ready");
});

test("only genuinely active stages set aria-busy semantics", () => {
  assert.equal(isBusyStage("extracting"), true);
  assert.equal(isBusyStage("translating_hy_mt2"), true);
  assert.equal(isBusyStage("candidate_ready"), false);
  assert.equal(isBusyStage("prepared"), false);
  assert.equal(isBusyStage("failed_retryable"), false);
  assert.equal(isBusyStage("unknown"), false);
});

// Summary
console.log(`\n=== Medical Writing Reference Progress Journey Tests ===`);
console.log(`Passed: ${passed}`);
console.log(`Failed: ${failed}`);
if (failures.length > 0) {
  console.log("\nFailures:");
  failures.forEach((f) => console.log(`  ✗ ${f.name}: ${f.message}`));
  process.exit(1);
} else {
  console.log("\nAll tests passed ✓");
  process.exit(0);
}
