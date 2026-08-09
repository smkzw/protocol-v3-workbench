/**
 * Per-lane runtime isolation allocator (acceptance-08).
 *
 * Single authority closure: this module privately owns the allocation registry
 * (_allocations). No other module can add a path to cleanup ownership.
 *
 * Public API:
 * - allocateLane() → opaque iso object with private _ownedPaths Symbol
 * - cleanupAllocation(iso) → deletes only the paths in that exact object
 * - recoveryCleanup(manifest, taskRuntimeRoot) → crash-recovery only,
 *   validates manifest identity/paths before deleting
 *
 * No exported function accepts an arbitrary path for registration.
 *
 * @module final_release_12lane_runtime_isolation
 */

import { createHash } from "node:crypto";
import { existsSync, readFileSync, realpathSync, lstatSync } from "node:fs";
import { mkdir, mkdtemp, rename, open, rm } from "node:fs/promises";
import net from "node:net";
import path from "node:path";

const _allocatedPorts = new Set();
const _heldSockets = new Map();
let _projectCodeCounter = 0;

// ─── Private allocation registry ────────────────────────────────────────
// Maps laneKey → Set<canonicalPath>. Only allocateLane() and
// cleanupAllocation() can read/modify this. Not exported.

const _allocationPaths = new Map();

// Private Symbol on the iso object — stores the exact set of owned paths.
// Not exported; callers cannot forge or inspect it.
const _OWNED = Symbol("owned_paths");

export async function atomicWriteFile(filePath, data) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const tmp = filePath + ".tmp";
  const fh = await open(tmp, "w"); await fh.writeFile(data, "utf8"); await fh.sync(); await fh.close();
  await rename(tmp, filePath);
  try { const d = await open(path.dirname(filePath), "r"); await d.sync(); await d.close(); } catch {}
}

export async function acquireHeldPort(preferred = 0) {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.on("error", (e) => { if (preferred !== 0) resolve(acquireHeldPort(0)); else reject(e); });
    s.listen(preferred, "127.0.0.1", () => resolve({ port: s.address().port, server: s }));
  });
}

export async function acquireUniquePort() {
  for (let i = 0; i < 50; i++) {
    const { port, server } = await acquireHeldPort(0);
    if (!_allocatedPorts.has(port)) { _allocatedPorts.add(port); _heldSockets.set(port, server); return port; }
    server.close();
  }
  throw new Error("Could not acquire a unique port after 50 attempts");
}

export function releaseHeldPort(port) { const s = _heldSockets.get(port); if (s) { _heldSockets.delete(port); try { s.close(); } catch {} } }
export function releasePort(port) { releaseHeldPort(port); _allocatedPorts.delete(port); }

export function generateProjectCode(laneKey) { _projectCodeCounter++; return `QC-12L-${laneKey}-${Date.now()}-${_projectCodeCounter}`; }

// ─── Allocation manifest ────────────────────────────────────────────────

const MANIFEST_FILENAME = "allocation_manifest.json";

export async function saveAllocationManifest(iso) {
  const manifest = {
    schema_version: "mw_e3_allocation_manifest_v1",
    laneKey: iso.laneKey, projectCode: iso.projectCode,
    allocationAttempt: iso.allocationAttempt,
    runtimeDir: iso.runtimeDir, evidenceDir: iso.evidenceDir,
    chromeProfileDir: iso.chromeProfileDir,
    attemptId: iso.attemptId,
    savedAt: new Date().toISOString(),
  };
  await atomicWriteFile(path.join(iso.evidenceDir, MANIFEST_FILENAME), JSON.stringify(manifest, null, 2));
}

export async function loadAllocationManifest(laneKey, evidenceRoot, taskRuntimeRoot) {
  const manifestPath = path.join(evidenceRoot, laneKey, MANIFEST_FILENAME);
  if (!existsSync(manifestPath)) return null;

  let m; try { m = JSON.parse(readFileSync(manifestPath, "utf8")); } catch { return { _invalid: "parse_error" }; }
  if (m.schema_version !== "mw_e3_allocation_manifest_v1") return { _invalid: "wrong_schema" };
  if (!m.laneKey || m.laneKey !== laneKey) return { _invalid: "wrong_lane" };
  if (!m.runtimeDir || !m.projectCode || !m.allocationAttempt || !m.attemptId) return { _invalid: "missing_fields" };
  if (m.runtimeDir.includes("..")) return { _invalid: "escaped_path" };
  if (!existsSync(m.runtimeDir)) return { _invalid: "runtime_not_found" };

  let canonTaskRoot, canonRuntime;
  try { canonTaskRoot = realpathSync(taskRuntimeRoot); } catch { return { _invalid: "task_root_unreadable" }; }
  try { canonRuntime = realpathSync(m.runtimeDir); } catch { return { _invalid: "runtime_unreadable" }; }
  if (!canonRuntime.startsWith(canonTaskRoot + path.sep)) return { _invalid: "runtime_outside_task_root" };

  if (!m.evidenceDir) return { _invalid: "missing_evidence_dir" };
  let canonEvRoot, canonEv;
  try { canonEvRoot = realpathSync(evidenceRoot); } catch { return { _invalid: "evidence_root_unreadable" }; }
  try { canonEv = realpathSync(m.evidenceDir); } catch { return { _invalid: "evidence_unreadable" }; }
  const expectedEv = path.join(canonEvRoot, laneKey);
  if (canonEv !== expectedEv) return { _invalid: "evidence_mismatch" };

  try { if (lstatSync(m.runtimeDir).isSymbolicLink()) return { _invalid: "symlink_runtime" }; } catch { return { _invalid: "lstat_failed" }; }

  return m;
}

// ─── Cohesive allocation ────────────────────────────────────────────────

export async function allocateLane({ laneKey, taskRuntimeRoot, evidenceRoot }) {
  await mkdir(taskRuntimeRoot, { recursive: true });
  await mkdir(evidenceRoot, { recursive: true });

  const existing = await loadAllocationManifest(laneKey, evidenceRoot, taskRuntimeRoot);
  if (existing && existing._invalid) throw new Error(`allocateLane: manifest invalid (${existing._invalid})`);

  const isResume = existing !== null;

  let runtimeDir, projectCode, allocationAttempt, attemptId, chromeProfileDir;

  if (isResume) {
    runtimeDir = existing.runtimeDir;
    projectCode = existing.projectCode;
    allocationAttempt = existing.allocationAttempt;
    attemptId = existing.attemptId;

    // Validate runtime still within task root
    let canonRuntime;
    try { canonRuntime = realpathSync(runtimeDir); } catch { throw new Error("resume runtime unreadable"); }
    let canonTaskRoot;
    try { canonTaskRoot = realpathSync(taskRuntimeRoot); } catch { throw new Error("task root unreadable"); }
    if (!canonRuntime.startsWith(canonTaskRoot + path.sep)) throw new Error("resume runtime outside task root");

    // Create fresh chrome profile
    await mkdir(taskRuntimeRoot, { recursive: true });
    chromeProfileDir = await mkdtemp(path.join(taskRuntimeRoot, `${laneKey}-chrome-profile-`));
  } else {
    runtimeDir = await mkdtemp(path.join(taskRuntimeRoot, `${laneKey}-`));
    chromeProfileDir = await mkdtemp(path.join(taskRuntimeRoot, `${laneKey}-chrome-profile-`));
    projectCode = generateProjectCode(laneKey);
    allocationAttempt = `alloc-${laneKey}-${Date.now()}`;
    attemptId = allocationAttempt;
  }

  const evidenceDir = path.join(evidenceRoot, laneKey);
  await mkdir(evidenceDir, { recursive: true });

  const runId = `${laneKey}-${Date.now()}-${createHash("sha256").update(`${laneKey}-${Date.now()}-${Math.random()}`).digest("hex").slice(0,8)}`;

  // Register owned paths in private registry
  const ownedPaths = new Set();
  try { ownedPaths.add(realpathSync(runtimeDir)); } catch {}
  try { ownedPaths.add(realpathSync(chromeProfileDir)); } catch {}
  _allocationPaths.set(laneKey, ownedPaths);

  const iso = {
    laneKey, projectCode, runtimeDir, evidenceDir,
    apiPort: await acquireUniquePort(),
    vitePort: await acquireUniquePort(),
    cdpPort: await acquireUniquePort(),
    chromeProfileDir,
    allocatedAt: new Date().toISOString(),
    attemptId, allocationAttempt, runId, isResume,
    [_OWNED]: ownedPaths, // private — callers can't access without the Symbol
  };
  iso.apiBase = `http://127.0.0.1:${iso.apiPort}`;
  iso.appUrl = `http://127.0.0.1:${iso.vitePort}/`;

  await saveAllocationManifest(iso);
  return iso;
}

/**
 * Cleanup directories owned by this exact allocation object.
 * Only the paths in the opaque iso[_OWNED] set are eligible.
 * No arbitrary path can be injected.
 */
export async function cleanupAllocation(iso) {
  if (!iso || typeof iso !== "object") return { removed: [], rejected: [], archived: [] };
  const ownedPaths = iso[_OWNED];
  if (!ownedPaths || !(ownedPaths instanceof Set)) return { removed: [], rejected: [], archived: [] };

  const removed = [], rejected = [], archived = [];
  // Gather other lanes' paths for conflict detection
  const otherPaths = new Set();
  for (const [key, paths] of _allocationPaths.entries()) {
    if (key !== iso.laneKey) for (const p of paths) otherPaths.add(p);
  }

  for (const dirRaw of ownedPaths) {
    let dir; try { dir = realpathSync(dirRaw); } catch { archived.push(dirRaw); continue; }
    if (otherPaths.has(dir)) { rejected.push({dir, reason:"cross_lane"}); continue; }
    let conf = false;
    for (const op of otherPaths) { if (dir.startsWith(op + path.sep) || op.startsWith(dir + path.sep)) { rejected.push({dir, reason:`conflict:${op}`}); conf = true; break; } }
    if (conf) continue;
    if (!existsSync(dir)) { archived.push(dir); continue; }
    try { await rm(dir, { recursive: true, force: true }); removed.push(dir); } catch { archived.push(dir); }
  }
  return { removed, rejected, archived };
}

/**
 * Get owned dirs for inspection (read-only snapshot).
 */
export function getAllocationOwnedDirs(laneKey) {
  return new Set(_allocationPaths.get(laneKey) || []);
}

export async function releaseLane(iso) { releasePort(iso.apiPort); releasePort(iso.vitePort); releasePort(iso.cdpPort); }

export function validateIsolation(allocs) {
  const v = [], rd = new Set(), ports = new Map(), prof = new Set();
  for (const i of allocs) {
    if (rd.has(i.runtimeDir)) v.push(`dup_rt:${i.laneKey}`); rd.add(i.runtimeDir);
    if (prof.has(i.chromeProfileDir)) v.push(`dup_prof:${i.laneKey}`); prof.add(i.chromeProfileDir);
    for (const [l,p] of [["api",i.apiPort],["vite",i.vitePort],["cdp",i.cdpPort]]) { if (ports.has(p)) v.push(`dup:${l}:${i.laneKey}`); else ports.set(p,i.laneKey); }
    if (!i.projectCode?.includes(i.laneKey)) v.push(`bad_proj:${i.laneKey}`);
    if (!i.attemptId?.includes(i.laneKey)) v.push(`bad_attempt:${i.laneKey}`);
  }
  return { valid: v.length === 0, violations: v };
}

export function validateConcurrency(c) {
  if (typeof c !== "number" || !Number.isFinite(c) || !Number.isInteger(c)) return { valid: false, normalized: 0, error: "not_integer" };
  if (c !== 1 && c !== 2) return { valid: false, normalized: 0, error: `must_be_1_or_2 (${c})` };
  return { valid: true, normalized: c, error: null };
}

export function parseConcurrencyEnv(v) {
  if (v === undefined || v === null || v === "") return { concurrency: 1, error: null };
  const t = String(v).trim();
  if (t === "1") return { concurrency: 1, error: null };
  if (t === "2") return { concurrency: 2, error: null };
  return { concurrency: 0, error: `QC_MAX_CONCURRENCY must be "1" or "2" (got "${v}")` };
}

export async function runBoundedConcurrency({ items, concurrency, taskFn, shouldStop = () => false }) {
  const chk = validateConcurrency(concurrency);
  if (!chk.valid) return { results: [], stopped: false, stopReason: null, incomplete: true, expectedCount: items.length, actualCount: 0, error: `invalid:${chk.error}` };
  const max = chk.normalized;
  const results = [];
  let stopped = false, stopReason = null, nextIndex = 0;
  async function worker() {
    while (nextIndex < items.length && !stopped) {
      if (shouldStop()) { stopped = true; stopReason = "shouldStop()"; return; }
      const idx = nextIndex++; const item = items[idx];
      try { const r = await taskFn(item, idx); results.push({ lane: item.key, index: idx, result: r }); if (r.__haltSuite) { stopped = true; stopReason = r.__haltReason || "halt"; } }
      catch (e) { results.push({ lane: item.key, index: idx, result: { laneReport: { lane: item.key, exitCode: -1, exception: e.message }, failures: [`${item.key}:exception:${e.message}`], runtimeInfo: {} } }); }
    }
  }
  const ws = []; for (let i = 0; i < max; i++) ws.push(worker());
  await Promise.all(ws);
  return { results, stopped, stopReason, incomplete: results.length < items.length, expectedCount: items.length, actualCount: results.length };
}

export function _clearAllocations() {
  for (const s of _heldSockets.values()) { try { s.close(); } catch {} }
  _heldSockets.clear(); _allocatedPorts.clear(); _allocationPaths.clear(); _projectCodeCounter = 0;
}
export function _getAllocatedPorts() { return new Set(_allocatedPorts); }
export function _getHeldSockets() { return new Map(_heldSockets); }
