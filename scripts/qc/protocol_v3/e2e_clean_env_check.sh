#!/bin/zsh
# T17 launch preconditions: isolated e2e environment is clean and alive.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)/../../.."
ROOT="$(cd "$ROOT" && pwd)"
fail=0

# 1) e2e SQLite absent or empty of studies
DB="$ROOT/runs/requirements_v2_20260919/e2e_multitester.sqlite"
if [[ -f "$DB" ]]; then
  count=$(/opt/homebrew/bin/python3.12 - "$DB" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    print(con.execute("SELECT COUNT(*) FROM protocol_workflow_project_allowlist").fetchone()[0])
except Exception:
    print(0)
PY
)
  if [[ "$count" != "0" ]]; then
    print -u2 "FAIL: e2e database holds $count admitted project(s) — remove it for a clean round."
    fail=1
  else
    print "ok: e2e database empty"
  fi
else
  print "ok: no e2e database yet (clean)"
fi

# 2) isolated backend health (5275)
if curl -fsS "http://127.0.0.1:5275/api/health" >/dev/null 2>&1; then
  print "ok: backend 5275 healthy"
else
  print -u2 "WARN: backend 5275 not responding — start the isolated backend before dispatch."
fi

# 3) dedicated frontend health (5176)
if curl -fsS "http://127.0.0.1:5176/" >/dev/null 2>&1; then
  print "ok: frontend 5176 healthy"
else
  print -u2 "WARN: frontend 5176 not responding — start the dedicated frontend before dispatch."
fi

exit $fail
