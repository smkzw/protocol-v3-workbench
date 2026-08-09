import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const appSource = await readFile(path.resolve(testDir, "../src/App.jsx"), "utf8");
const styleSource = await readFile(path.resolve(testDir, "../src/styles.css"), "utf8");

const writingStart = appSource.indexOf("function WritingPage({");
const writingEnd = appSource.indexOf("function approvalTypeLabel(", writingStart);
assert.ok(writingStart >= 0 && writingEnd > writingStart, "WritingPage source must be available");
const writingSource = appSource.slice(writingStart, writingEnd);

assert.doesNotMatch(
  writingSource,
  /当前章节正文尚未完成段落级加载，AI修订暂时关闭/,
  "Paragraph-load state must not render the retired warning-banner copy",
);
assert.match(
  writingSource,
  /const paragraphLoadPending = !isStudySchemaSection[\s\S]*?&& !sectionContentAvailable;/,
  "Paragraph-load state must remain explicit",
);
assert.match(
  writingSource,
  /!isStudySchemaSection && \(!sectionHasBackendBinding \|\| !editorSessionAvailable\)/,
  "Persistent warning row must be limited to true session or binding blockers",
);
assert.match(
  writingSource,
  /id="writing-ai-unavailable-reason"[\s\S]*?当前章节正文仍在加载；完成后可使用AI修订。/,
  "Paragraph-load reason must remain available as a low-emphasis status note",
);
assert.ok(
  (writingSource.match(/aria-describedby=\{paragraphLoadPending \? "writing-ai-unavailable-reason" : undefined\}/g) || []).length >= 4,
  "Disabled AI controls must reference the exact paragraph-load reason",
);
assert.match(
  writingSource,
  /const aiRevisionDisabled = Boolean\(aiRevisionUnavailableReason\);/,
  "AI controls must remain disabled whenever an unavailable reason exists",
);
assert.match(
  writingSource,
  /const freezeReadinessNeedsAction = !isStudySchemaSection[\s\S]*?&& authoringJourneyAvailable[\s\S]*?&& editorSessionAvailable[\s\S]*?&& !workingCopyLoading/,
  "Freeze/version blockers must not appear before a real document editing session exists",
);
assert.match(
  styleSource,
  /\.writing-editor-availability-note\s*\{[\s\S]*?color:\s*var\(--muted\);/,
  "Availability note must use low-emphasis styling",
);

console.log(JSON.stringify({
  passed: true,
  verified: [
    "retired full-width paragraph-load warning removed",
    "AI disabled state preserved",
    "exact reason linked to disabled controls",
    "low-emphasis footer note retained",
  ],
}, null, 2));
