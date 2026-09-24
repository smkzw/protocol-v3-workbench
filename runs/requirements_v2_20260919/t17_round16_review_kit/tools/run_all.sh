#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python "$ROOT/tools/run_reservation_probes.py"
node "$ROOT/tools/run_cancel_probes.mjs"
python "$ROOT/tools/run_route_controls.py"
