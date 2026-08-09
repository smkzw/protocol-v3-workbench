import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const styles = await readFile(path.resolve(testDir, "../src/styles.css"), "utf8");

assert.match(
  styles,
  /\.authoring-competitor-drawer-body\s*\{[\s\S]*?overflow-y:\s*auto;[\s\S]*?overflow-x:\s*hidden;/,
  "The competitor drawer body must scroll vertically without exposing a horizontal scrollbar",
);
assert.match(
  styles,
  /\.writing-reference-panel\.is-embedded\s+\.writing-reference-candidate-filters\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(120px,\s*0\.45fr\)\s+auto;/,
  "Embedded candidate filters must fit the drawer instead of inheriting desktop-page minimum columns",
);

console.log("medical-writing competitor drawer overflow: 2 passed");
