/**
 * Isolation behavior QC — acceptance-08.
 * All executable behavior, no source-string assertions.
 */
import { strict as assert } from "node:assert";
import { existsSync, mkdtempSync, rmSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const __scriptDir = path.dirname(fileURLToPath(import.meta.url));
import { EXPECTED_STUDIES_12LANE } from "./final_release_12lane_config.mjs";
import { StableHash, MultiRootStableHash } from "./final_release_12lane_stable_hash.mjs";
import { registerProcess, writeOwnershipRecord, saveJobLocators, checkResume, isPidAlive, _clearRegistry, countUnresolvedLocators } from "./final_release_12lane_process_ownership.mjs";
import { allocateLane, validateIsolation, runBoundedConcurrency, parseConcurrencyEnv, validateConcurrency, cleanupAllocation, _clearAllocations } from "./final_release_12lane_runtime_isolation.mjs";

let passed = 0, failed = 0;
const failures = [], tests = [];
function test(name, fn) { return { name, fn }; }
function tmpDir(p) { return mkdtempSync(path.join(tmpdir(), p)); }
function cleanup(d) { try { rmSync(d, { recursive: true, force: true }); } catch {} }

tests.push(test("IS-01: Two lanes unique state", async () => {
  _clearAllocations(); _clearRegistry();
  const tr = tmpDir("is01-"), er = tmpDir("is01-er-");
  try {
    const a = await allocateLane({ laneKey: EXPECTED_STUDIES_12LANE[0].key, taskRuntimeRoot: tr, evidenceRoot: er });
    const b = await allocateLane({ laneKey: EXPECTED_STUDIES_12LANE[1].key, taskRuntimeRoot: tr, evidenceRoot: er });
    assert.notEqual(a.apiPort, b.apiPort);
    assert.notEqual(a.runtimeDir, b.runtimeDir);
    assert.ok(validateIsolation([a, b]).valid);
  } finally { cleanup(tr); cleanup(er); _clearAllocations(); _clearRegistry(); }
}));

tests.push(test("IS-02: Stable hash detects changes", async () => {
  const d = tmpDir("is02-");
  try {
    await writeFile(path.join(d, "f.txt"), "a");
    await writeFile(path.join(d, ".hidden"), "h");
    const sh = new StableHash(d); const b = await sh.snapshot();
    assert.equal(b.fileCount, 2);
    await writeFile(path.join(d, "f.txt"), "changed");
    assert.ok(StableHash.diff(b, await sh.snapshot()).hasChanges);
  } finally { cleanup(d); }
}));

tests.push(test("IS-03: registerProcess rejects pid<=0", async () => {
  _clearRegistry();
  let t0 = false, tN = false;
  try { registerProcess({ laneKey: "T", role: "x", pid: 0 }); } catch { t0 = true; }
  try { registerProcess({ laneKey: "T", role: "x", pid: -1 }); } catch { tN = true; }
  assert.ok(t0); assert.ok(tN);
  _clearRegistry();
}));

tests.push(test("IS-04: Bounded concurrency + failure-stop", async () => {
  let mx = 0, cur = 0;
  const { stopped } = await runBoundedConcurrency({
    items: Array.from({ length: 6 }, (_, i) => ({ key: `L${i}` })), concurrency: 2,
    taskFn: async (l) => { cur++; mx = Math.max(mx, cur); await new Promise(r => setTimeout(r, 30)); cur--; return l.key === "L3" ? { __haltSuite: true, __haltReason: "halt" } : {}; },
  });
  assert.ok(mx <= 2); assert.ok(stopped);
}));

tests.push(test("IS-05: checkResume rejects malformed/mismatched", async () => {
  _clearRegistry();
  const ev = tmpDir("is05-");
  try {
    assert.equal((await checkResume("T", ev, "P1", "A1")).resume, false);
    await saveJobLocators("T", { s: { job_id: "j", terminal_status: "completed" } }, ev, "P1", "A1");
    assert.equal((await checkResume("T", ev, "P1", "A1")).resume, true);
    assert.equal((await checkResume("T", ev, "WRONG", "A1")).rejected, true);
  } finally { cleanup(ev); _clearRegistry(); }
}));

tests.push(test("IS-06: All 12 lanes isolation", async () => {
  _clearAllocations(); _clearRegistry();
  const tr = tmpDir("is06-"), er = tmpDir("is06-er-");
  try {
    const allocs = [];
    for (const l of EXPECTED_STUDIES_12LANE) allocs.push(await allocateLane({ laneKey: l.key, taskRuntimeRoot: tr, evidenceRoot: er }));
    assert.equal(allocs.length, 12);
    assert.ok(validateIsolation(allocs).valid);
  } finally { cleanup(tr); cleanup(er); _clearAllocations(); _clearRegistry(); }
}));

tests.push(test("IS-07: Concurrency strict", async () => {
  assert.equal(parseConcurrencyEnv("1").concurrency, 1);
  assert.equal(parseConcurrencyEnv("2").concurrency, 2);
  assert.ok(parseConcurrencyEnv("1x").error);
  assert.ok(parseConcurrencyEnv("3").error);
  assert.ok(!validateConcurrency(3).valid);
}));

tests.push(test("IS-08: countUnresolvedLocators strict", async () => {
  assert.equal(countUnresolvedLocators({ locators: { a: { terminal_status: "completed" } } }), 0);
  assert.equal(countUnresolvedLocators({ locators: { a: { terminal_status: "failed" } } }), 1);
  assert.equal(countUnresolvedLocators(null), 1);
  assert.equal(countUnresolvedLocators({}), 1);
}));

// D1: cleanupAllocation with wrong object deletes nothing
tests.push(test("IS-09: cleanupAllocation with wrong object deletes zero", async () => {
  _clearAllocations(); _clearRegistry();
  const d = tmpDir("is09-");
  try {
    const r = await cleanupAllocation({ laneKey: "FAKE" });
    assert.equal(r.removed.length, 0);
    assert.ok(existsSync(d));
  } finally { cleanup(d); _clearAllocations(); _clearRegistry(); }
}));

// D1: No marker file created
tests.push(test("IS-10: No forgeable marker files", async () => {
  _clearAllocations(); _clearRegistry();
  const tr = tmpDir("is10-"), er = tmpDir("is10-er-");
  try {
    const a = await allocateLane({ laneKey: "IS10", taskRuntimeRoot: tr, evidenceRoot: er });
    assert.ok(!existsSync(path.join(a.runtimeDir, ".mw_e3_alloc")), "No marker file");
    assert.ok(a.allocationAttempt);
    assert.equal(a.attemptId, a.allocationAttempt);
  } finally { cleanup(tr); cleanup(er); _clearAllocations(); _clearRegistry(); }
}));

// D1: Forged manifest pointing to victim dir fails
tests.push(test("IS-11: Forged manifest adversary cannot delete", async () => {
  _clearAllocations(); _clearRegistry();
  const tr = tmpDir("is11-"), er = tmpDir("is11-er-"), victim = tmpDir("is11-victim-");
  try {
    writeFileSync(path.join(victim, ".mw_e3_alloc"), JSON.stringify({ laneKey: "IS11", taskRoot: tr }));
    const laneEv = path.join(er, "IS11");
    mkdirSync(laneEv, { recursive: true });
    writeFileSync(path.join(laneEv, "allocation_manifest.json"), JSON.stringify({
      schema_version: "mw_e3_allocation_manifest_v1", laneKey: "IS11",
      projectCode: "QC-FAKE", allocationAttempt: "fake", attemptId: "fake",
      runtimeDir: victim, evidenceDir: laneEv, chromeProfileDir: victim,
    }));
    let threw = false;
    try { await allocateLane({ laneKey: "IS11", taskRuntimeRoot: tr, evidenceRoot: er }); }
    catch { threw = true; }
    assert.ok(threw);
    assert.ok(existsSync(victim));
    // cleanupAllocation with fake object also can't delete
    const r = await cleanupAllocation({ laneKey: "IS11" });
    assert.equal(r.removed.length, 0);
    assert.ok(existsSync(victim));
  } finally { cleanup(tr); cleanup(er); cleanup(victim); _clearAllocations(); _clearRegistry(); }
}));

// D2: Resume reuses immutable identity
tests.push(test("IS-12: Resume immutable identity", async () => {
  _clearAllocations(); _clearRegistry();
  const tr = tmpDir("is12-"), er = tmpDir("is12-er-");
  try {
    const a = await allocateLane({ laneKey: "IS12", taskRuntimeRoot: tr, evidenceRoot: er });
    const origAtt = a.attemptId, origAa = a.allocationAttempt;
    await _clearAllocations(); _clearRegistry();
    const b = await allocateLane({ laneKey: "IS12", taskRuntimeRoot: tr, evidenceRoot: er });
    assert.ok(b.isResume);
    assert.equal(b.attemptId, origAtt);
    assert.equal(b.allocationAttempt, origAa);
    assert.notEqual(b.runId, a.runId);
  } finally { cleanup(tr); cleanup(er); _clearAllocations(); _clearRegistry(); }
}));

// D1: No authority-minting/channel exports
tests.push(test("IS-13: No authority exports in either module", async () => {
  const po = await import("./final_release_12lane_process_ownership.mjs");
  for (const banned of ["_issueAllocationToken", "registerOwnedDir", "_createAllocation", "_registerAllocatedDir", "_allocatorCreateDir", "_allocatorResumeDir", "_initAllocation", "_ALLOC", "_getAllocatorChannel", "cleanupLaneEphemeralDirs"]) {
    assert.ok(!(banned in po), `process_ownership must not export ${banned}`);
  }
  const ri = await import("./final_release_12lane_runtime_isolation.mjs");
  for (const banned of ["_ALLOC", "_getAllocatorChannel", "registerOwnedDir", "_registerAllocatedDir", "_allocatorCreateDir", "_allocatorResumeDir", "_initAllocation", "cleanupLaneEphemeralDirs"]) {
    assert.ok(!(banned in ri), `runtime_isolation must not export ${banned}`);
  }
}));

async function runAll() {
  console.log("E3 12-Lane Isolation QC — acceptance-08");
  console.log("============================================================");
  for (const { name, fn } of tests) {
    try { await fn(); passed++; }
    catch (e) { failed++; failures.push({ name, message: e.message }); }
  }
  console.log("============================================================");
  console.log(`Passed: ${passed}`); console.log(`Failed: ${failed}`);
  if (failures.length) { console.log("\nFailures:"); for (const f of failures) console.log(`  X ${f.name}\n    ${f.message}`); }
  console.log("============================================================");
  if (failed > 0) process.exitCode = 1;
}
runAll();
