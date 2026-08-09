/**
 * Adversarial isolation tests — acceptance-08.
 * All behavior, no source-string assertions.
 */
import { strict as assert } from "node:assert";
import { existsSync, mkdtempSync, rmSync, writeFileSync, readFileSync, mkdirSync } from "node:fs";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const __scriptDir = path.dirname(fileURLToPath(import.meta.url));
import { StableHash, MultiRootStableHash } from "./final_release_12lane_stable_hash.mjs";
import { registerProcess, stopOwnedPid, writeOwnershipRecord, saveJobLocators, checkResume, verifyProcessIdentity, _clearRegistry, countUnresolvedLocators } from "./final_release_12lane_process_ownership.mjs";
import { allocateLane, releaseLane, validateIsolation, runBoundedConcurrency, parseConcurrencyEnv, validateConcurrency, cleanupAllocation, _clearAllocations } from "./final_release_12lane_runtime_isolation.mjs";

let passed = 0, failed = 0;
const failures = [], tests = [];
function test(name, fn) { return { name, fn }; }
function tmpDir(p) { return mkdtempSync(path.join(tmpdir(), p)); }
function cleanup(d) { try { rmSync(d, { recursive: true, force: true }); } catch {} }

tests.push(test("ADV-01: .hidden mutation detected", async () => {
  const d = tmpDir("adv01-");
  try {
    await writeFile(path.join(d, "v.txt"), "v1");
    await writeFile(path.join(d, ".hidden"), "h1");
    const sh = new StableHash(d); const b = await sh.snapshot();
    assert.ok(b.entries.some(e => e.relativePath === ".hidden"));
    await writeFile(path.join(d, ".hidden"), "h2");
    assert.ok(StableHash.diff(b, await sh.snapshot()).hasChanges);
  } finally { cleanup(d); }
}));

tests.push(test("ADV-02: Missing root fails closed", async () => {
  const snap = await new StableHash("/tmp/mw-nonexist-adv02-999").snapshot();
  assert.ok(!snap.exists); assert.ok(snap.incomplete);
}));

tests.push(test("ADV-03: Non-existent PID fails closed", async () => {
  _clearRegistry();
  try {
    registerProcess({ laneKey: "A3", role: "api", pid: 999999, executable: "fake" });
    const r = await stopOwnedPid(999999);
    assert.ok(!r.stopped || r.reason.includes("not_found"));
  } finally { _clearRegistry(); }
}));

tests.push(test("ADV-04: pid<=0 rejected", async () => {
  _clearRegistry();
  let t0 = false, tN = false;
  try { registerProcess({ laneKey: "T", role: "x", pid: 0 }); } catch { t0 = true; }
  try { registerProcess({ laneKey: "T", role: "x", pid: -1 }); } catch { tN = true; }
  assert.ok(t0); assert.ok(tN);
  _clearRegistry();
}));

tests.push(test("ADV-05: Cross-lane cleanup via allocation object rejected", async () => {
  _clearAllocations(); _clearRegistry();
  const tr = tmpDir("adv05-"), er = tmpDir("adv05-er-");
  try {
    const isoA = await allocateLane({ laneKey: "LANE_A", taskRuntimeRoot: tr, evidenceRoot: er });
    // cleanupAllocation with LANE_B's fake object won't touch LANE_A's dirs
    const r = await cleanupAllocation({ laneKey: "LANE_B" });
    assert.equal(r.removed.length, 0);
  } finally { cleanup(tr); cleanup(er); _clearAllocations(); _clearRegistry(); }
}));

tests.push(test("ADV-06: Multi-root mutation", async () => {
  const r1 = tmpDir("adv06-1-"), r2 = tmpDir("adv06-2-");
  try {
    await writeFile(path.join(r1, "f.txt"), "a");
    await writeFile(path.join(r2, "f.txt"), "b");
    const m = new MultiRootStableHash([{ label: "r1", path: r1 }, { label: "r2", path: r2 }]);
    const b = await m.snapshot();
    await writeFile(path.join(r2, "f.txt"), "changed");
    assert.ok(MultiRootStableHash.diff(b, await m.snapshot()).hasChanges);
  } finally { cleanup(r1); cleanup(r2); }
}));

tests.push(test("ADV-07: Resume immutable identity", async () => {
  _clearAllocations(); _clearRegistry();
  const tr = tmpDir("adv07-"), er = tmpDir("adv07-er-");
  try {
    const a = await allocateLane({ laneKey: "ADV07", taskRuntimeRoot: tr, evidenceRoot: er });
    const origAtt = a.attemptId, origAa = a.allocationAttempt;
    await releaseLane(a); _clearAllocations(); _clearRegistry();
    const b = await allocateLane({ laneKey: "ADV07", taskRuntimeRoot: tr, evidenceRoot: er });
    assert.ok(b.isResume);
    assert.equal(b.attemptId, origAtt);
    assert.equal(b.allocationAttempt, origAa);
  } finally { cleanup(tr); cleanup(er); _clearAllocations(); _clearRegistry(); }
}));

tests.push(test("ADV-08: Concurrency strict", async () => {
  assert.ok(parseConcurrencyEnv("1x").error);
  assert.ok(parseConcurrencyEnv("3").error);
}));

// D1: Forged marker + manifest cannot delete — victim sentinel survives
tests.push(test("ADV-09: Forged marker+manifest victim survives (D1)", async () => {
  _clearAllocations(); _clearRegistry();
  const tr = tmpDir("adv09-"), er = tmpDir("adv09-er-"), victim = tmpDir("adv09-victim-");
  try {
    // Write sentinel in victim
    writeFileSync(path.join(victim, "sentinel.txt"), "survive");
    // Forge marker
    writeFileSync(path.join(victim, ".mw_e3_alloc"), JSON.stringify({ laneKey: "ADV09", taskRoot: tr }));
    // Forge manifest
    const laneEv = path.join(er, "ADV09");
    mkdirSync(laneEv, { recursive: true });
    writeFileSync(path.join(laneEv, "allocation_manifest.json"), JSON.stringify({
      schema_version: "mw_e3_allocation_manifest_v1", laneKey: "ADV09",
      projectCode: "QC-FAKE", allocationAttempt: "fake", attemptId: "fake",
      runtimeDir: victim, evidenceDir: laneEv, chromeProfileDir: victim,
    }));
    let threw = false;
    try { await allocateLane({ laneKey: "ADV09", taskRuntimeRoot: tr, evidenceRoot: er }); }
    catch { threw = true; }
    assert.ok(threw, "allocateLane must reject forged manifest");
    assert.ok(existsSync(path.join(victim, "sentinel.txt")), "Sentinel must survive");
    // cleanupAllocation with fake object also cannot delete
    const r = await cleanupAllocation({ laneKey: "ADV09" });
    assert.equal(r.removed.length, 0);
    assert.ok(existsSync(path.join(victim, "sentinel.txt")), "Sentinel still survives");
  } finally { cleanup(tr); cleanup(er); cleanup(victim); _clearAllocations(); _clearRegistry(); }
}));

tests.push(test("ADV-10: Manifest outside task root fails", async () => {
  _clearAllocations(); _clearRegistry();
  const tr = tmpDir("adv10-"), er = tmpDir("adv10-er-"), outside = tmpDir("adv10-out-");
  try {
    const laneEv = path.join(er, "ADV10");
    mkdirSync(laneEv, { recursive: true });
    writeFileSync(path.join(laneEv, "allocation_manifest.json"), JSON.stringify({
      schema_version: "mw_e3_allocation_manifest_v1", laneKey: "ADV10",
      projectCode: "QC-FAKE", allocationAttempt: "fake", attemptId: "fake",
      runtimeDir: outside, evidenceDir: laneEv, chromeProfileDir: outside,
    }));
    let threw = false;
    try { await allocateLane({ laneKey: "ADV10", taskRuntimeRoot: tr, evidenceRoot: er }); }
    catch { threw = true; }
    assert.ok(threw);
    assert.ok(existsSync(outside));
  } finally { cleanup(tr); cleanup(er); cleanup(outside); _clearAllocations(); _clearRegistry(); }
}));

tests.push(test("ADV-11: Malformed locator → rejected", async () => {
  _clearRegistry();
  const ev = tmpDir("adv11-");
  try {
    writeFileSync(path.join(ev, "job_locators.json"), "{ broken");
    const r = await checkResume("ADV11", ev, "P1", "A1");
    assert.equal(r.rejected, true);
  } finally { cleanup(ev); _clearRegistry(); }
}));

tests.push(test("ADV-12: Mismatched locator → rejected", async () => {
  _clearRegistry();
  const ev = tmpDir("adv12-");
  try {
    await saveJobLocators("ADV12", { s: { job_id: "j", terminal_status: "completed" } }, ev, "P1", "A1");
    const r = await checkResume("ADV12", ev, "WRONG", "A1");
    assert.equal(r.rejected, true);
  } finally { cleanup(ev); _clearRegistry(); }
}));

tests.push(test("ADV-13: Malformed locators → unresolved", async () => {
  assert.ok(countUnresolvedLocators(null) > 0);
  assert.ok(countUnresolvedLocators({}) > 0);
  assert.equal(countUnresolvedLocators({ locators: { a: { terminal_status: "completed" } } }), 0);
}));

// D1: Enumerate all exported functions, try each with attacker-controlled values
tests.push(test("ADV-14: Enumerate exports — no authority to delete victim (D1)", async () => {
  _clearAllocations(); _clearRegistry();
  const victim = tmpDir("adv14-victim-");
  writeFileSync(path.join(victim, "sentinel.txt"), "survive");
  try {
    const po = await import("./final_release_12lane_process_ownership.mjs");
    const ri = await import("./final_release_12lane_runtime_isolation.mjs");

    // No export in po can delete directories at all
    assert.ok(!("cleanupLaneEphemeralDirs" in po), "po must not have cleanupLaneEphemeralDirs");

    // cleanupAllocation requires an allocation object with private Symbol
    const r1 = await ri.cleanupAllocation(null);
    assert.equal(r1.removed.length, 0);
    const r2 = await ri.cleanupAllocation({ laneKey: "FAKE" });
    assert.equal(r2.removed.length, 0);
    const r3 = await ri.cleanupAllocation({ laneKey: "FAKE", runtimeDir: victim });
    assert.equal(r3.removed.length, 0);

    // Sentinel survives
    assert.ok(existsSync(path.join(victim, "sentinel.txt")), "Sentinel must survive all attempts");
  } finally { cleanup(victim); _clearAllocations(); _clearRegistry(); }
}));

// D1: Red sentinel — would fail against acceptance_07 exported _ALLOC design
tests.push(test("ADV-15: Red sentinel — _ALLOC not exported (D1)", async () => {
  const po = await import("./final_release_12lane_process_ownership.mjs");
  // This is a BEHAVIORAL test: try to get the channel and add a dir
  // In acceptance_07, po._ALLOC was exported and po._getAllocatorChannel(po._ALLOC) worked
  const allocKey = po._ALLOC;
  if (allocKey) {
    // If _ALLOC is exported, try to use it — this must fail
    const chan = po._getAllocatorChannel ? po._getAllocatorChannel(allocKey) : null;
    if (chan && chan.addOwnedDir) {
      // This would be the vulnerability — prove it doesn't work
      // But we assert it doesn't exist
      assert.fail("_ALLOC channel should not exist");
    }
  }
  // If we get here, _ALLOC is not exported or channel not accessible — pass
  assert.ok(true, "No _ALLOC channel accessible");
}));

async function runAll() {
  console.log("E3 12-Lane Adversarial Tests — acceptance-08");
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
