import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const appPath = path.resolve(testDir, "../src/App.jsx");
const stylePath = path.resolve(testDir, "../src/styles.css");
const appSource = await readFile(appPath, "utf8");
const styleSource = await readFile(stylePath, "utf8");

function sourceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.ok(start >= 0 && end > start, `Unable to isolate ${startMarker} -> ${endMarker}`);
  return source.slice(start, end);
}

const inboxPolicySource = sourceBetween(
  appSource,
  "const DIRECT_MEDICAL_DECISION_ITEM_TYPES",
  "function EmptyProjectOverview(",
);
const inboxPolicy = new Function(`${inboxPolicySource}
  return { isUnreadMedicalDecisionItem, medicalDecisionItems };
`)();

const baseItem = {
  unread: true,
  needs_action: true,
  title: "待处理事项",
  summary: "",
  status: "待处理",
  action_label: "查看",
  source_type: "test",
};

const policyCases = [
  [{ ...baseItem, item_type: "risk" }, true, "unread medical risk"],
  [{ ...baseItem, item_type: "approval" }, true, "approval decision"],
  [{ ...baseItem, item_type: "picos_decision" }, true, "PICOS decision"],
  [{ ...baseItem, item_type: "eligibility_action" }, true, "eligibility decision"],
  [{ ...baseItem, item_type: "handoff" }, true, "cross-module decision"],
  [{ ...baseItem, item_type: "risk", unread: false }, false, "read risk"],
  [{ ...baseItem, item_type: "ai_review", title: "AI任务待处理", status: "AI运行失败" }, false, "AI validation failure"],
  [{ ...baseItem, item_type: "ai_review", status: "待医学确认" }, false, "generic AI review"],
  [{ ...baseItem, item_type: "source_ready", status: "待OCR/VLM", action_label: "补充解析" }, false, "technical source preparation"],
  [{ ...baseItem, item_type: "quality_gate", summary: "复杂表格可能未形成locator" }, false, "technical quality log"],
  [{ ...baseItem, item_type: "source_ready", status: "内容不一致", action_label: "确认沿用" }, true, "source content validation"],
  [{ ...baseItem, item_type: "data_health", summary: "字段含义需医学判断" }, true, "medical data-content decision"],
];

for (const [item, expected, label] of policyCases) {
  assert.equal(inboxPolicy.isUnreadMedicalDecisionItem(item), expected, label);
}

const overviewSource = sourceBetween(appSource, "function OverviewPage(", "function AiGatewayPanel(");
assert.match(overviewSource, /decisionItems\.slice\(0,\s*10\)/, "Inbox must render filtered decision items");
assert.match(overviewSource, /统一工作收件箱 · \$\{decisionItems\.length\} 项待决策/, "Title must use filtered count");
assert.doesNotMatch(overviewSource, /所有AI和交接内容均需医学经理确认/, "Retired blanket medical-approval copy");
assert.doesNotMatch(overviewSource, /AI审计/, "AI audit must not be promoted on overview");

const aiPanelSource = sourceBetween(appSource, "function AiGatewayPanel(", "function SourceHealthList(");
assert.doesNotMatch(aiPanelSource, /ai-run-list|recentRuns/, "Historical AI run log must not render on dashboard");

const writingSource = sourceBetween(appSource, "function WritingPage({", "function approvalTypeLabel(");
assert.match(writingSource, /className="writing-editor-blocker"/, "Editor must use one compact blocker row");
assert.match(writingSource, /<details>/, "Internal diagnosis must be collapsed by default");
assert.match(writingSource, /!workingCopyAuthoritative && !editorBlocker/, "Quarantine warning must not duplicate the combined blocker");
assert.doesNotMatch(writingSource, /className="writing-freeze-readiness-bar"/, "Duplicate freeze banner retired");
assert.doesNotMatch(writingSource, /className=\{`writing-study-consistency-bar/, "Duplicate consistency banner retired");
for (const capability of ["保存工作副本", "重新加载", "版本与恢复", "预览 Word", "正式 Word"]) {
  assert.ok(writingSource.includes(capability), `Working-copy capability retained: ${capability}`);
}

assert.match(styleSource, /\.working-copy-actions button\s*\{[\s\S]*?min-height:\s*26px;/, "Compact work-copy buttons");
assert.match(styleSource, /\.writing-editor-blocker\s*\{[\s\S]*?min-height:\s*34px;/, "Compact editor blocker");
assert.match(styleSource, /\.inbox-scope-note\s*\{/, "Compact inbox scope note");

console.log(JSON.stringify({
  passed: true,
  policyCases: policyCases.length,
  verified: [
    "AI validation and audit items are excluded",
    "only unread real medical decisions enter the inbox",
    "source-content validation remains actionable",
    "editor warnings are consolidated behind one compact blocker",
    "working-copy capabilities remain present",
  ],
}, null, 2));
