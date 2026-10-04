#!/bin/zsh
# R26 自检第4次（本轮）修复后重启 5301：让下一次自检在含修复的代码上复验。
# 环境与 start_5301_round27.sh 完全一致（当前运行进程亦无云端 key env）。
ROOT="/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313"
ISO="$ROOT/runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime"
LOG="$ROOT/runs/requirements_v2_20260919/t17_round27_loop/backend_5301_restart_after_selfcheck4_fixes.log"
mkdir -p "$(dirname "$LOG")"
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
