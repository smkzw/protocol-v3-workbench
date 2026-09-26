#!/bin/sh
# G0 gate selftest runner (A002/A003/A004 + R1 layout + R2 fingerprint).
# Usage: tools/acceptance/selftest/run_all.sh [evidence_dir]
# Saves the raw GATE_JSON output into the evidence dir (default under runs/).
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EVIDENCE_DIR="${1:-$REPO_ROOT/runs/requirements_v2_20260919/t18_g0_acceptance_gate_evidence}"
mkdir -p "$EVIDENCE_DIR"
OUT="$EVIDENCE_DIR/selftest_all.json"
echo "== gate selftest all ==" | tee "$OUT"
python3 "$REPO_ROOT/tools/acceptance/run_acceptance_gate.py" --selftest all 2>&1 | tee -a "$OUT"
exit "${PIPESTATUS:-0}"
