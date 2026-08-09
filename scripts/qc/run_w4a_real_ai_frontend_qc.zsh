#!/bin/zsh
set -euo pipefail
setopt NULL_GLOB

ROOT="/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/workbench"
STABLE_RUNTIME="/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/runtime"
ENV_FILE="${WORKBENCH_AI_ENV_FILE:-$HOME/.config/cms-medical-workbench/ai-runtime.env}"
OUTPUT_DIR="${QC_OUTPUT_DIR:-$ROOT/records/active_slices/medical_writing_w4a_20260725/browser_qc_real_ai}"
API_PORT="${QC_API_PORT:-8912}"
WEB_PORT="${QC_WEB_PORT:-5176}"
CHROME_DEBUG_PORT="${QC_CHROME_DEBUG_PORT:-9572}"
RUNTIME_DIR="$(mktemp -d /tmp/mw-w4a-real-ai-runtime.XXXXXX)"
API_PID=""
WEB_PID=""

cleanup() {
  if [[ -n "$WEB_PID" ]]; then
    kill -TERM "$WEB_PID" 2>/dev/null || true
    wait "$WEB_PID" 2>/dev/null || true
  fi
  if [[ -n "$API_PID" ]]; then
    kill -TERM "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  rm -rf "$RUNTIME_DIR"
}
trap cleanup EXIT INT TERM

if [[ ! -r "$ENV_FILE" ]]; then
  print -u2 "Independent AI environment is unavailable: $ENV_FILE"
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT_DIR"/*.png "$OUTPUT_DIR"/prefill_frontend_qc.json \
  "$OUTPUT_DIR"/api.log "$OUTPUT_DIR"/vite.log "$OUTPUT_DIR"/runtime_dir.txt
cp -R "$STABLE_RUNTIME"/. "$RUNTIME_DIR"/
print -r -- "$RUNTIME_DIR" > "$OUTPUT_DIR/runtime_dir.txt"

set -a
source "$ENV_FILE"
set +a

export WORKBENCH_RUNTIME_DIR="$RUNTIME_DIR"
export WORKBENCH_CLIENT_CONTRACT_MODE="enforce"

cd "$ROOT"
python3 -m uvicorn services.api.app.main:app \
  --app-dir "$ROOT" \
  --host 127.0.0.1 \
  --port "$API_PORT" \
  > "$OUTPUT_DIR/api.log" 2>&1 &
API_PID=$!

VITE_API_PROXY_TARGET="http://127.0.0.1:$API_PORT" \
  npm --prefix frontend run dev -- \
  --host 127.0.0.1 \
  --port "$WEB_PORT" \
  --strictPort \
  > "$OUTPUT_DIR/vite.log" 2>&1 &
WEB_PID=$!

for attempt in {1..120}; do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then
    break
  fi
  if (( attempt == 120 )); then
    print -u2 "Isolated API did not become ready on port $API_PORT"
    exit 3
  fi
  sleep 1
done

for attempt in {1..120}; do
  if curl -fsS "http://127.0.0.1:$WEB_PORT/runtime-build.json" >/dev/null 2>&1; then
    break
  fi
  if (( attempt == 120 )); then
    print -u2 "Isolated frontend did not become ready on port $WEB_PORT"
    exit 4
  fi
  sleep 1
done

QC_ISOLATED_RUNTIME=1 \
QC_OUTPUT_DIR="$OUTPUT_DIR" \
APP_URL="http://127.0.0.1:$WEB_PORT/" \
API_URL="http://127.0.0.1:$API_PORT" \
CHROME_DEBUG_PORT="$CHROME_DEBUG_PORT" \
  node frontend/tests/medical_writing_authoring_prefill_frontend_qc.mjs
