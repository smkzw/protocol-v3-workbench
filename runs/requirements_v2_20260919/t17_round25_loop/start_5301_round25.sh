#!/bin/zsh
# round25: 按 HANDOFF_0924V2_BATCH1 §一配方重启 5301（加载0928仲裁增量）
# env 五件套照抄 round22/23 配方；PYTHONPATH=services/api:.
ROOT="/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313"
ISO="$ROOT/runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime"
LOG="$ROOT/runs/requirements_v2_20260919/t17_round25_loop/backend_5301_round25_restart.log"
cd "$ROOT" || exit 1
PYTHONPATH="services/api:." \
WORKBENCH_RUNTIME_DIR="$ISO" \
WORKBENCH_AI_SETTINGS_PATH="$ISO/ai_provider_settings.json" \
WORKBENCH_AI_ROLE_SETTINGS_PATH="$ISO/ai_role_bindings.json" \
WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1 \
WORKBENCH_PROTOCOL_V3_WORKFLOW_DB="$ROOT/runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/protocol_v3_product.sqlite" \
nohup /opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python \
  -m uvicorn app.main:app --host 127.0.0.1 --port 5301 >> "$LOG" 2>&1 &
echo "launched pid $!"
