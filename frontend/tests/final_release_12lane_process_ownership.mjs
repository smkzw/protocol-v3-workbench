/**
 * Process ownership tracker (acceptance-08).
 *
 * This module does NOT own, register, or delete directories. It manages only
 * process PIDs, job locators, and process ownership records. Directory
 * allocation and cleanup authority lives entirely in runtime_isolation.mjs
 * behind a private closure — no exported function in this module can add a
 * path to any cleanup registry.
 *
 * @module final_release_12lane_process_ownership
 */

import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { mkdir, rename, writeFile, open } from "node:fs/promises";
import path from "node:path";

export const PROCESS_OWNERSHIP_SCHEMA_VERSION = "mw_e3_process_ownership_v2";

// ─── Process registry (PIDs only — no directory authority) ──────────────

const _registry = new Map();
const _jobLocators = new Map();

// ─── OS process identity ────────────────────────────────────────────────

function readProcessStartTime(pid) {
  if (!pid || typeof pid !== "number" || pid <= 0) return null;
  try { return execSync(`ps -p ${pid} -o lstart=`, { encoding: "utf8", timeout: 5000, stdio: ["pipe", "pipe", "pipe"] }).trim(); }
  catch { return null; }
}

function readProcessCommand(pid) {
  if (!pid || typeof pid !== "number" || pid <= 0) return null;
  try { return execSync(`ps -p ${pid} -o args=`, { encoding: "utf8", timeout: 5000, stdio: ["pipe", "pipe", "pipe"] }).trim(); }
  catch { return null; }
}

export function captureProcessIdentity(pid) {
  const st = readProcessStartTime(pid), cmd = readProcessCommand(pid);
  if (!st || !cmd) return null;
  return { startTime: st, command: cmd };
}

export function verifyProcessIdentity(pid, expectedStart, expectedCmd) {
  if (!expectedStart || !expectedCmd) return { verified: false, reason: "null_expected_identity" };
  const cur = readProcessStartTime(pid), cmd = readProcessCommand(pid);
  if (!cur || !cmd) return { verified: false, reason: "process_not_found_or_unreadable" };
  if (cur !== expectedStart) return { verified: false, reason: "start_time_mismatch" };
  const et = expectedCmd.split(/\s+/).map(t => t.split("/").pop()).filter(t => t.length > 2 && !["node","python","python3","usr","bin","local","Applications"].includes(t));
  const ct = cmd.split(/\s+/).map(t => t.split("/").pop());
  if (!et.some(t => ct.includes(t))) return { verified: false, reason: "command_mismatch" };
  return { verified: true, reason: null };
}

function getDescendantPids(pid) {
  if (!pid || typeof pid !== "number" || pid <= 0) return [];
  try {
    const out = execSync(`pgrep -P ${pid} 2>/dev/null || true`, { encoding: "utf8", timeout: 5000, stdio: ["pipe", "pipe", "pipe"] }).trim();
    const ch = out.split("\n").filter(Boolean).map(Number);
    const all = [...ch];
    for (const c of ch) all.push(...getDescendantPids(c));
    return all;
  } catch { return []; }
}

function killProcessGroup(pgid, signal = "SIGTERM") {
  try { process.kill(-pgid, signal); return true; } catch { return false; }
}

// ─── Process registration ───────────────────────────────────────────────

export function registerProcess({ laneKey, role, pid, executable = process.execPath, assignedPort = null, runtimeDir = null, profileDir = null, childScript = null, pgid = null }) {
  if (!laneKey) throw new Error("registerProcess: laneKey required");
  if (!role) throw new Error("registerProcess: role required");
  if (typeof pid !== "number" || pid <= 0) throw new Error(`registerProcess: pid must be positive (got ${pid})`);
  const osId = captureProcessIdentity(pid);
  const entry = { laneKey, role, pid, parentPid: process.pid, pgid: pgid || pid, executable, startIdentity: osId ? osId.startTime : null, osCommand: osId ? osId.command : null, registeredAt: new Date().toISOString(), assignedPort, runtimeDir, profileDir, childScript, alive: true };
  if (!_registry.has(laneKey)) _registry.set(laneKey, []);
  _registry.get(laneKey).push(entry);
  return entry;
}

export function markProcessExited(laneKey, pid) {
  const procs = _registry.get(laneKey);
  if (!procs) return;
  for (const p of procs) { if (p.pid === pid) p.alive = false; }
}

export function isPidAlive(pid) {
  if (!pid || typeof pid !== "number" || pid <= 0) return false;
  try { process.kill(pid, 0); return true; } catch { return false; }
}

export async function stopOwnedPid(pid, signal = "SIGTERM", graceMs = 3000) {
  if (typeof pid !== "number" || pid <= 0) return { stopped: false, reason: "invalid_pid" };
  let owned = null;
  for (const procs of _registry.values()) { const f = procs.find((p) => p.pid === pid); if (f) { owned = f; break; } }
  if (!owned) return { stopped: false, reason: "pid_not_owned" };
  const v = verifyProcessIdentity(pid, owned.startIdentity, owned.osCommand);
  if (!v.verified) return { stopped: false, reason: v.reason };
  if (!isPidAlive(pid)) return { stopped: true, reason: "already_exited" };
  const desc = getDescendantPids(pid);
  for (const d of desc) { try { process.kill(d, "SIGTERM"); } catch {} }
  killProcessGroup(owned.pgid, signal);
  try { process.kill(pid, signal); } catch {}
  const deadline = Date.now() + graceMs;
  while (Date.now() < deadline) {
    if (!isPidAlive(pid)) {
      const rem = getDescendantPids(pid);
      for (const d of rem) { try { process.kill(d, "SIGKILL"); } catch {} }
      return { stopped: true, reason: "graceful_pgid_exit" };
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  const killV = verifyProcessIdentity(pid, owned.startIdentity, owned.osCommand);
  if (!killV.verified) return { stopped: false, reason: `identity_changed:${killV.reason}` };
  for (const d of getDescendantPids(pid)) { try { process.kill(d, "SIGKILL"); } catch {} }
  killProcessGroup(owned.pgid, "SIGKILL");
  try { process.kill(pid, "SIGKILL"); } catch {}
  await new Promise((r) => setTimeout(r, 1000));
  for (const d of getDescendantPids(pid)) { try { process.kill(d, "SIGKILL"); } catch {} }
  const alive = isPidAlive(pid);
  return { stopped: !alive, reason: alive ? "still_alive" : "sigkill_exit" };
}

export async function stopLaneProcesses(laneKey) {
  const procs = _registry.get(laneKey) || [];
  const stopped = [], skipped = [], identityFailures = [];
  const ordered = [...procs].sort((a, b) => (({child:0,chrome:1,vite:2,api:3})[a.role] ?? 99) - (({child:0,chrome:1,vite:2,api:3})[b.role] ?? 99));
  for (const p of ordered) {
    if (!p.alive || !isPidAlive(p.pid)) { skipped.push(p.pid); markProcessExited(laneKey, p.pid); continue; }
    const r = await stopOwnedPid(p.pid);
    if (r.stopped) { stopped.push(p.pid); markProcessExited(laneKey, p.pid); }
    else { skipped.push(p.pid); if (r.reason?.includes("identity") || r.reason?.includes("mismatch") || r.reason?.includes("null")) identityFailures.push({pid:p.pid,reason:r.reason}); }
  }
  return { stopped, skipped, identityFailures };
}

// ─── Job locators ───────────────────────────────────────────────────────

export async function saveJobLocators(laneKey, locators, evidenceDir, projectCode, attemptId) {
  const fp = path.join(evidenceDir, "job_locators.json");
  await mkdir(path.dirname(fp), { recursive: true });
  const record = { schema_version: "mw_e3_job_locators_v1", laneKey, projectCode, attemptId, savedAt: new Date().toISOString(), locators };
  const tmp = fp + ".tmp";
  const fh = await open(tmp, "w"); await fh.writeFile(JSON.stringify(record, null, 2), "utf8"); await fh.sync(); await fh.close();
  await rename(tmp, fp);
  try { const d = await open(path.dirname(fp), "r"); await d.sync(); await d.close(); } catch {}
  _jobLocators.set(laneKey, record);
}

export async function loadJobLocators(laneKey, evidenceDir, expectedProjectCode, expectedAttemptId) {
  const fp = path.join(evidenceDir, "job_locators.json");
  if (!existsSync(fp)) return null;
  let r; try { r = JSON.parse(readFileSync(fp, "utf8")); } catch { return { malformed: true }; }
  if (r.schema_version !== "mw_e3_job_locators_v1") return { malformed: true };
  if (r.laneKey !== laneKey) return { mismatched: true };
  if (!r.projectCode || r.projectCode !== expectedProjectCode) return { mismatched: true };
  if (!r.attemptId || r.attemptId !== expectedAttemptId) return { mismatched: true };
  _jobLocators.set(laneKey, r);
  return r;
}

export async function checkResume(laneKey, evidenceDir, expectedProjectCode, expectedAttemptId) {
  const result = await loadJobLocators(laneKey, evidenceDir, expectedProjectCode, expectedAttemptId);
  if (!result) return { resume: false, locators: null, attemptId: null, rejected: false };
  if (result.malformed || result.mismatched) return { resume: false, locators: null, attemptId: null, rejected: true };
  return { resume: true, locators: result, attemptId: result.attemptId || null, rejected: false };
}

export function countUnresolvedLocators(rec) {
  if (!rec || typeof rec !== "object") return 1;
  if (!rec.locators || typeof rec.locators !== "object") return 1;
  let u = 0;
  for (const [, l] of Object.entries(rec.locators)) { if (!l || typeof l !== "object" || !l.terminal_status || l.terminal_status !== "completed") u++; }
  return u;
}

// ─── Records ────────────────────────────────────────────────────────────

export async function writeOwnershipRecord(laneKey, evidenceDir, ownedDirs) {
  const procs = _registry.get(laneKey) || [];
  for (const p of procs) p.alive = isPidAlive(p.pid);
  const rec = { schemaVersion: PROCESS_OWNERSHIP_SCHEMA_VERSION, laneKey, parentPid: process.pid, parentExecutable: process.execPath, recordedAt: new Date().toISOString(), processes: procs.map(p => ({...p})), ownedDirs: ownedDirs || [] };
  const fp = path.join(evidenceDir, "process_ownership.json");
  await mkdir(path.dirname(fp), { recursive: true });
  await writeFile(fp, JSON.stringify(rec, null, 2), "utf8");
  return rec;
}

// ─── Testing helpers ────────────────────────────────────────────────────

export function getRegistry() { return new Map(_registry); }
export function _clearRegistry() { _registry.clear(); _jobLocators.clear(); }
export { readProcessStartTime, readProcessCommand };
