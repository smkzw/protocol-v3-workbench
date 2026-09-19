#!/bin/zsh
# 独立端到端测试后端：清洁数据库 + deepseek profile
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DB="$ROOT/runs/mw_protocol_v3_unified_tests_20260919/e2e_test.sqlite"
rm -f "$DB" "$DB-wal" "$DB-shm" "$DB.artifacts" -rf 2>/dev/null
mkdir -p "$(dirname "$DB")" "$ROOT/runs/mw_protocol_v3_unified_tests_20260919/e2e_runtime"
# Pass through the AI runtime credentials/contract (deepseek profile needs
# them; without them the synopsis import AI call fails 'provider disabled').
ENV_FILE="${WORKBENCH_AI_ENV_FILE:-$HOME/.config/cms-medical-workbench/ai-runtime.env}"
set -a
source "$ENV_FILE"
set +a
env -i \
  PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin \
  HOME=/Users/smkzw \
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ \
  LANG=en_US.UTF-8 PYTHONNOUSERSITE=1 PYTHONPATH="services/api:packages:." \
  DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  WORKBENCH_AI_PROVIDER=deepseek \
  WORKBENCH_AI_TRANSPORT=openai_compatible \
  WORKBENCH_AI_BASE_URL=https://api.deepseek.com/v1 \
  WORKBENCH_AI_MODEL=deepseek-v4-flash \
  WORKBENCH_AI_DEPLOYMENT_PROFILE=local_private_clinical \
  WORKBENCH_AI_EXPECTED_RESPONSE_MODEL=deepseek-flash \
  WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1 \
  WORKBENCH_RUNTIME_DIR="$ROOT/runs/mw_protocol_v3_unified_tests_20260919/e2e_runtime" \
  WORKBENCH_PROTOCOL_V3_WORKFLOW_DB="$DB" \
  WORKBENCH_PROTOCOL_V3_PRODUCT_PROFILE=deepseek \
  WORKBENCH_PROTOCOL_V3_MAX_INPUT_BYTES=2000000 \
  "$ROOT/runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python" -m uvicorn \
  services.api.app.main:app --host 127.0.0.1 --port 5275 --log-level warning
