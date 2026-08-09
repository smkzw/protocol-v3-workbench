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
  if (start < 0 || end < 0) {
    throw new Error(`Unable to isolate source contract: ${startMarker} -> ${endMarker}`);
  }
  return source.slice(start, end);
}

function requireIncludes(source, value, label) {
  if (!source.includes(value)) throw new Error(`${label}: missing ${value}`);
}

const writingPage = sourceBetween(
  appSource,
  "function WritingPage({",
  "function approvalTypeLabel(",
);
const freezeHandler = sourceBetween(
  writingPage,
  "const submitWorkingCopyFreeze = (operation) => {",
  "const recoverWorkingCopyBinding = (operation) => {",
);
const recoveryHandler = sourceBetween(
  writingPage,
  "const recoverWorkingCopyBinding = (operation) => {",
  "const sectionThreads =",
);
const revisionActionHandler = sourceBetween(
  writingPage,
  "const submitRevisionAction = async (thread, suggestion, action) => {",
  "const applyApprovedRevision = async",
);
const revisionApplyHandler = sourceBetween(
  writingPage,
  "const applyApprovedRevision = async",
  "const createWorkingCopy =",
);
const historyLoader = sourceBetween(
  writingPage,
  "const refreshVersionHistory = (signal) => {",
  "useEffect(() => {",
);

if (writingPage.includes("/approval-gate")) {
  throw new Error("WritingPage still calls the retired medical-writing approval-gate endpoint");
}

for (const forbiddenCopy of [
  "待医学批准",
  "医学批准快照",
  "重新医学批准",
  "不等同于医学批准",
  "医学审批门",
]) {
  if (writingPage.includes(forbiddenCopy)) {
    throw new Error(`WritingPage still renders retired approval copy: ${forbiddenCopy}`);
  }
}

for (const [value, label] of [
  ["/medical-writing/freeze-readiness", "project freeze readiness"],
  ["/freeze-history", "section freeze history"],
  ["/quarantined-history", "quarantined working-copy history"],
  ["freeze-current-version", "freeze endpoint"],
  ["unfreeze", "unfreeze endpoint"],
  ["accept-and-bind", "accept-and-bind endpoint"],
  ["revert-authoritative-baseline", "authoritative baseline endpoint"],
]) {
  requireIncludes(writingPage, value, label);
}

for (const [source, value, label] of [
  [freezeHandler, 'method: "POST"', "freeze/unfreeze POST"],
  [freezeHandler, "expected_working_copy_revision", "freeze revision precondition"],
  [freezeHandler, "expected_study_definition_sha256", "freeze StudyDefinition binding"],
  [recoveryHandler, 'method: "POST"', "binding recovery POST"],
  [recoveryHandler, "acknowledge_binding: true", "binding recovery acknowledgement"],
  [recoveryHandler, "bindingRecoveryReason.trim()", "binding recovery reason"],
  [historyLoader, "response.status === 404 ? null", "optional quarantine history"],
  [appSource, "function isRevisionThreadSelectedByAuthor(status)", "author-selected status helper"],
  [appSource, '"author_selected", "medically_approved", "accepted_pending_medical_approval"', "current and legacy selected statuses"],
  [revisionActionHandler, 'await applyApprovedRevision(payload.thread, { fromSelection: true });', "candidate select attempts working-copy write"],
  [revisionApplyHandler, "!isRevisionThreadSelectedByAuthor(thread.status)", "apply does not depend on retired approval-only status"],
  [revisionApplyHandler, "候选处置已记录，但写入失败", "candidate selected but write failed recovery copy"],
  [revisionApplyHandler, "使用“重试写入”", "write retry instruction"],
]) {
  requireIncludes(source, value, label);
}

for (const [source, value, label] of [
  [writingPage, 'workingCopy?.freeze_status === "frozen"', "freeze-derived editor lock"],
  [writingPage, "freezeReadiness?.ready === true", "final Word freeze readiness gate"],
  [appSource, "当前作者确认版本 / 已冻结", "author freeze status copy"],
  [appSource, 'author_selected: "医学作者已选用"', "author selected status copy"],
  [writingPage, "确认并冻结", "author freeze action copy"],
  [writingPage, "解除冻结", "unfreeze action copy"],
  [writingPage, "隔离历史", "quarantine disclosure copy"],
  [writingPage, "确认绑定此版本", "accept-and-bind action copy"],
  [writingPage, "恢复权威源基线", "authoritative baseline action copy"],
  [writingPage, "当前文档需重绑定后再冻结或正式导出", "compact actionable blocked state"],
  [writingPage, "医学作者点击“选用并写入”即形成医学决定", "author selection is the medical decision"],
  [writingPage, "候选保持已选用并显示重试写入", "non-atomic candidate write boundary"],
  [writingPage, "医学作者已选用，待写入", "candidate write retry state"],
  [writingPage, "历史候选已选用，待写入", "legacy selected candidate migration state"],
]) {
  requireIncludes(source, value, label);
}

for (const className of [
  ".writing-editor-blocker",
  ".writing-version-panel",
  ".writing-version-disclosure",
  ".writing-binding-recovery-form",
  ".revision-application-band.needs-write-retry",
  ".revision-application-actions",
]) {
  requireIncludes(styleSource, className, "version/recovery styling");
}

for (const retiredPersistentWarning of [
  'className="writing-freeze-readiness-bar"',
  'className={`writing-study-consistency-bar',
]) {
  if (writingPage.includes(retiredPersistentWarning)) {
    throw new Error(`WritingPage still renders duplicate persistent warning: ${retiredPersistentWarning}`);
  }
}

console.log(JSON.stringify({
  passed: true,
  appPath,
  stylePath,
  verified: [
    "no writing-editor approval-gate call",
    "freeze/unfreeze/readiness/history endpoint contracts",
    "quarantine accept/revert reasoned recovery contracts",
    "author-confirmation and freeze copy boundary",
    "candidate selection write-retry boundary without fake success",
  ],
}, null, 2));
