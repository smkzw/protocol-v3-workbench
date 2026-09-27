"""LIVE rehearsal runner for the round21 lifecycle orchestrator.

Only ever touches the two managed servers (oMLX 8001 / MTPLX 8002).
Every subcommand is read-only unless its name says otherwise.  Run from
anywhere; audit/state/pidfile paths resolve against the repo root.

Usage:
  python3 lively_run.py adopt        # step0: one-time adoption of pidfile pid
  python3 lively_run.py status       # read-only status + sentinel
  python3 lively_run.py ensure triage
  python3 lively_run.py ensure translation
  python3 lively_run.py release triage "reason" [--force]
  python3 lively_run.py begin ENDPOINT [SECONDS]   # drill: hold a sentinel count
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from services.api.app import model_lifecycle_orchestrator as orch  # noqa: E402


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    o = orch._default()

    if cmd == "status":
        doc = o.status()
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0

    if cmd == "adopt":
        doc = o.adopt("mtplx", operator="实现师",
                      evidence="LIVE step0: pidfile+cmdline(runtime-venv/"
                               "mtplx.server.openai/--port 8002)+served id+"
                               "footprint 全部核验后收编")
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0 if doc.get("adopted") else 1

    if cmd == "ensure":
        doc = o.ensure(sys.argv[2])
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0 if doc.get("status") == "ok" else 1

    if cmd == "release":
        phase = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else "lively"
        force = "--force" in sys.argv
        doc = o.release(phase, reason, force=force)
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0 if doc.get("status") in ("ok", "noop") else 1

    if cmd == "begin":
        endpoint = sys.argv[2]
        seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
        orch.gateway_dispatch_begin(endpoint)
        print(f"sentinel count held at "
              f"{orch.sentinel_snapshot(endpoint)} for {seconds}s")
        time.sleep(seconds)
        orch.gateway_dispatch_end(endpoint)
        print(f"released: {orch.sentinel_snapshot(endpoint)}")
        return 0

    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
