// Focused deterministic smoke test for the disposable harness process gate.
import assert from "node:assert/strict";
import process from "node:process";
import { runChildWithTimeout } from "./final_matrix_process.mjs";

const completed = await runChildWithTimeout(
  process.execPath,
  ["-e", "process.stdout.write('ok');"],
  { cwd: process.cwd() },
  5000,
);
assert.equal(completed.status, 0);
assert.equal(completed.timedOut, false);
assert.equal(completed.stdout, "ok");

const timedOut = await runChildWithTimeout(
  process.execPath,
  ["-e", "setTimeout(() => {}, 30000);"],
  { cwd: process.cwd(), graceMs: 250 },
  100,
);
assert.equal(timedOut.status, null);
assert.equal(timedOut.timedOut, true);
assert.ok(["SIGTERM", "SIGKILL"].includes(timedOut.timeoutSignal));

const descendant = await runChildWithTimeout(
  process.execPath,
  ["-e", "const {spawn}=require('node:child_process'); const c=spawn(process.execPath,['-e','setTimeout(()=>{},30000)'],{stdio:['ignore','ignore','ignore']}); console.log(c.pid); setTimeout(()=>{},30000);"],
  { cwd: process.cwd(), graceMs: 250 },
  250,
);
const descendantPid = Number(String(descendant.stdout || "").trim().split(/\s+/)[0]);
assert.ok(descendantPid > 0);
let descendantAlive = true;
try { process.kill(descendantPid, 0); } catch { descendantAlive = false; }
assert.equal(descendantAlive, false);
console.log(JSON.stringify({
  completed: { status: completed.status },
  timedOut: { status: timedOut.status, timeoutSignal: timedOut.timeoutSignal },
  descendant: { status: descendant.status, timeoutSignal: descendant.timeoutSignal, pid: descendantPid, alive: descendantAlive },
}));
