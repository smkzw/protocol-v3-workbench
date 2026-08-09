import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const FEATURE_ROOT = fileURLToPath(new URL("./", import.meta.url));
const SOURCE_EXTENSIONS = new Set([".mjs", ".jsx", ".css"]);
const FORBIDDEN_LITERALS = Object.freeze([
  ["known MG-K10 project literal", /\bMG[-_ ]?K10\b/i],
  ["known Ruxolitinib project literal", /\bRuxolitinib\b/i],
  ["known MY008 project literal", /\bMY008\b/i],
  ["known MY009 project literal", /\bMY009\b/i],
  ["known company literal", /康哲|朗来/],
  ["local absolute path", /(?:^|["'`\s])\/(?:Users|private|tmp)\//],
  ["file URL", /file:\/\//i],
]);

function productionFiles(directory = FEATURE_ROOT) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return productionFiles(path);
    if (!SOURCE_EXTENSIONS.has(extname(entry.name))) return [];
    if (/\.test\.(?:mjs|jsx|css)$/.test(entry.name)) return [];
    return [path];
  });
}

const findings = [];
for (const path of productionFiles()) {
  const source = readFileSync(path, "utf8");
  for (const [label, pattern] of FORBIDDEN_LITERALS) {
    const match = source.match(pattern);
    if (match) {
      findings.push({
        label,
        file: relative(FEATURE_ROOT, path),
        match: match[0],
      });
    }
  }
}

assert.deepEqual(
  findings,
  [],
  "feature-owned production frontend must remain project-neutral and path-neutral",
);

const adversarial = [
  "MG-K10",
  "Ruxolitinib",
  "MY008",
  "MY009",
  "康哲",
  "朗来",
  "/Users/example/source.xlsx",
  "/private/var/tmp/source.xlsx",
  "file:///Users/example/source.xlsx",
];
for (const literal of adversarial) {
  assert.ok(
    FORBIDDEN_LITERALS.some(([, pattern]) => pattern.test(literal)),
    `guard must reject ${literal}`,
  );
}

console.log(`medicalMonitoringProjectNeutralContract: ${productionFiles().length} production files scanned`);

