#!/usr/bin/env python3
"""Wave 1 bounded-volume observer: segmented polling until convergence.

Polls (a) the durable job record and (b) per-study item status counts for
the three wave studies.  Convergence: batch no longer running AND zero
items in transient states, or 40 minutes elapsed, or two consecutive polls
with zero status delta (no-progress stop per the standing red line).
"""
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

DB = "runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime/writing_reference.sqlite3"
JOBS = "runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime/medical_writing_durable_jobs.sqlite3"
JOB_ID = "mwjob_63c5033bb91a953223d06d85"
WAVE_NCTS = ("NCT02176291", "NCT03283670", "NCT03113968")
BATCH = "wref_translation_batch_79e7f4e51e7270b75688e8e9"
PROJECT = "proj_user_fad9f64f3151"
DEADLINE_S = 23 * 60  # remaining budget of the 40-min window from dispatch 14:14Z
POLL_S = 120

def snapshot():
    con = sqlite3.connect(DB)
    try:
        rows = con.execute(
            """
            SELECT json_extract(payload_json,'$.nct_id'), generation_status, COUNT(*)
            FROM writing_reference_translation_batch_items
            WHERE project_id=? AND batch_id=?
              AND json_extract(payload_json,'$.nct_id') IN (?,?,?)
            GROUP BY 1,2
            """,
            (PROJECT, BATCH, *WAVE_NCTS),
        ).fetchall()
    finally:
        con.close()
    return {f"{n}|{s}": c for n, s, c in rows}

def job_row():
    con = sqlite3.connect(JOBS)
    try:
        return con.execute(
            "SELECT status, attempt_count, substr(progress_json,1,220), error_summary "
            "FROM durable_mw_jobs WHERE job_id=?", (JOB_ID,)
        ).fetchone()
    finally:
        con.close()

start = time.time()
prev = None
no_progress_strikes = 0
poll_no = 0
while True:
    poll_no += 1
    elapsed = int(time.time() - start)
    snap = snapshot()
    st, att, prog, err = job_row()
    print(
        f"[poll {poll_no:02d} t+{elapsed//60:02d}:{elapsed%60:02d}] job={st} "
        f"attempt={att} progress={prog} err={err[:80]}",
        flush=True,
    )
    for key in sorted(snap):
        print(f"    {key} = {snap[key]}", flush=True)
    delta = "" if prev is None else {
        k: snap.get(k, 0) - prev.get(k, 0)
        for k in set(snap) | set(prev)
        if snap.get(k, 0) != prev.get(k, 0)
    }
    if prev is not None:
        print(f"    delta vs prev poll: {delta or 'NONE'}", flush=True)
        if not delta:
            no_progress_strikes += 1
        else:
            no_progress_strikes = 0
    prev = snap
    transient = sum(c for k, c in snap.items() if any(
        t in k for t in ("running", "planning", "translating", "pending", "queued")
    ))
    done = st in ("completed", "failed", "cancelled") and transient == 0
    if done:
        print(f"[converged] job terminal ({st}) and transient items = 0", flush=True)
        break
    if no_progress_strikes >= 3:
        print("[stopped] three consecutive polls with zero delta (no-progress rule)", flush=True)
        break
    if elapsed + POLL_S > DEADLINE_S:
        print("[deadline] 40-minute observation budget reached", flush=True)
        break
    time.sleep(POLL_S)
print("[observer end]", flush=True)
