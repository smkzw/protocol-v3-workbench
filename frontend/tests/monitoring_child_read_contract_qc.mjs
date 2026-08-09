import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../src/features/medical-monitoring/", import.meta.url);
const field = await readFile(new URL("MedicalMonitoringFieldMappingPanel.jsx", root), "utf8");
const protocol = await readFile(new URL("MedicalMonitoringProtocolPreparationPanel.jsx", root), "utf8");
const release = await readFile(new URL("MedicalMonitoringRuleReleasePanel.jsx", root), "utf8");
const daily = await readFile(new URL("MedicalMonitoringDailyRunPanel.jsx", root), "utf8");

assert.match(field, /clearMappingState\(\);\s*setError\(""\);\s*setMessage\(""\);\s*setBusy\(true\);/);
assert.match(field, /nextError\?\.name !== "AbortError"\)\s*\{\s*clearMappingState\(\);/);
assert.match(field, /const nextJobs = applyStatus\(status\);\s*setError\(""\);/);

assert.match(protocol, /setVersions\(\[\]\);\s*setSelectedVersionId\(""\);\s*setStatus\(null\);/);
assert.match(protocol, /setVersions\(\[\]\);[\s\S]*?setRuleTemplateStates\(\{\}\);[\s\S]*?setError\(errorText\(nextError, "已确认方案版本读取失败"\)/);
assert.match(protocol, /setStatus\(null\);\s*setCandidateDecisions\(\{\}\);\s*setRuleTemplateStates\(\{\}\);\s*setPollStopped\(true\);/);
assert.match(protocol, /payload: null,\s*loading: false,\s*error: errorText\(nextError, "规则建议状态读取失败"\)/);

assert.match(release, /const \[auxiliaryReadError, setAuxiliaryReadError\] = useState\(""\);/);
assert.match(release, /setAuxiliaryReadError\(ruleReleaseErrorText\(/);
assert.match(release, /auxiliaryReadError && \(/);
assert.match(release, /<p className="monitoring-rule-release-error" role="alert">/);

assert.match(daily, /const \[readinessError, setReadinessError\] = useState\(""\);/);
assert.match(daily, /const \[aiProgressError, setAiProgressError\] = useState\(""\);/);
assert.match(daily, /setReadinessError\(apiErrorMessage\(nextError, "日常监查就绪状态读取失败"\)\)/);
assert.match(daily, /setAiProgressError\(apiErrorMessage\(nextError, "AI复核进度读取失败"\)\)/);
assert.match(daily, /readinessError && <p className="monitoring-daily-run-error" role="alert">/);
assert.match(daily, /aiProgressError && <p className="monitoring-daily-run-error" role="alert">/);

console.log(JSON.stringify({
  fieldMapping: "stale-read-clears",
  protocolPreparation: "stale-read-clears",
  ruleRelease: "auxiliary-read-visible",
  dailyRun: "readiness-and-ai-progress-errors-visible",
}));
