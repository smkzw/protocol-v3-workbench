#!/bin/zsh
# 独立端到端测试后端：清洁数据库 + deepseek profile
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DB="$ROOT/runs/mw_protocol_v3_unified_tests_20260919/e2e_test.sqlite"
rm -f "$DB" "$DB-wal" "$DB-shm" "$DB.artifacts" -rf 2>/dev/null
mkdir -p "$(dirname "$DB")"
env -i \
  PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin \
  HOME=/Users/smkzw \
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ \
  LANG=en_US.UTF-8 PYTHONNOUSERSITE=1 PYTHONPATH="services/api:packages:." \
  WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1 \
  WORKBENCH_PROTOCOL_V3_WORKFLOW_DB="$DB" \
  WORKBENCH_PROTOCOL_V3_PRODUCT_PROFILE=deepseek \
  WORKBENCH_PROTOCOL_V3_MAX_INPUT_BYTES=2000000 \
  "$ROOT/runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python" -m uvicorn \
  services.api.app.main:app --host 127.0.0.1 --port 5275 --log-level warning
