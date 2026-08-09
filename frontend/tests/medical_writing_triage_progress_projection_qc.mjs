import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const source = await readFile(
  path.resolve(
    testDir,
    "../src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx",
  ),
  "utf8",
);

const start = source.indexOf("function ResearchPipelineBanner({");
assert.ok(start >= 0, "ResearchPipelineBanner must exist");
const banner = source.slice(start, source.indexOf("\nfunction ", start + 1));

assert.match(
  banner,
  /const percent = Number\.isFinite\(Number\(pipeline\.percent\)\)[\s\S]*?\? Number\(pipeline\.percent\)[\s\S]*?: stage === "triaging"[\s\S]*?\? triageProgress\.percent/,
  "The main progress bar must prefer backend weighted pipeline progress",
);
assert.match(
  banner,
  /const childPercent = Number\.isFinite\(Number\(pipeline\.child_percent\)\)[\s\S]*?\? Number\(pipeline\.child_percent\)[\s\S]*?: stage === "triaging"[\s\S]*?\? Number\(triageProgress\.percent \|\| 0\)/,
  "The current substep must retain its own live progress projection",
);
assert.match(
  banner,
  /stage === "triaging" && triageProgress\.total_chunks > 0[\s\S]*?独立AI正在处理已锁定的竞品；已完成分块会自动保留。/,
  "Triage detail must not repeat the retry-time completed count",
);
assert.match(
  banner,
  /\{childCompleted\}\/\{childTotal\} · \{childPercent\}%/,
  "One compact live completed/total and substep-percent counter must remain visible",
);

console.log("medical-writing triage progress projection: 3 passed");
