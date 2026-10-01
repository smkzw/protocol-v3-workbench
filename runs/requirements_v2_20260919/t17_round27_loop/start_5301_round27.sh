#!/bin/zsh
# round27: 在 round26 配方基础上补 ENV-01/ENV-02 环境项（2026-09-28 第26轮复盘）
#
# 变更点（相对 start_5301_round26.sh）：
# 1) 云端 key 预检（只读不改）：
#    isolated_runtime/ai_provider_settings.json 里启用的 profile 需要 5 个 key：
#      DEEPSEEK_API_KEY / PADDLE_OCR_API_KEY / OPENCODE_API_KEY /
#      CMS_ROUTER_API_KEY / MTPLX_API_KEY
#    key 的"值"由集成人核定——在启动前于同一终端 export 即可（nohup 子进程
#    自动继承全部环境变量，本脚本无需也不应内置任何 key 值）。缺失时打印
#    预检告警（R26 实测：OPENCODE_API_KEY 缺失使 zen fallback 在不可达时只能
#    空耗 300 秒×3；PADDLE_OCR_API_KEY 缺失使 R788 Protocol 下载后 OCR 全链
#    冻结——两条 P0 现场报告的环境根因）。
# 2) ENV-02 预算旋钮（代码内已设默认值 1200s/1800s，可用环境覆盖，同样经
#    继承生效，无需在此展开）：
#      WORKBENCH_AI_TASK_TIMEOUT_<TASK_TYPE>
#      WORKBENCH_AI_TASK_LADDER_BUDGET_<TASK_TYPE>
# 3) 红线不变：本脚本只起 5301，不碰 live 8910 / 医学监查 / 共享 runtime；
#    模型服务器只经编排器；前端启动必须显式 VITE_API_PROXY_TARGET=5301。
ROOT="/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313"
ISO="$ROOT/runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime"
LOG="$ROOT/runs/requirements_v2_20260919/t17_round27_loop/backend_5301_round27_restart.log"
mkdir -p "$(dirname "$LOG")"
cd "$ROOT" || exit 1

# ---- 预检：如实报告缺失的 key（不阻断启动；本地模型路由不依赖这些 key） ----
MISSING=()
for KEY_ENV in DEEPSEEK_API_KEY PADDLE_OCR_API_KEY OPENCODE_API_KEY CMS_ROUTER_API_KEY MTPLX_API_KEY; do
  if [ -z "${(P)KEY_ENV}" ]; then
    MISSING+=("$KEY_ENV")
  fi
done
if (( ${#MISSING[@]} > 0 )); then
  echo "[round27 preflight] 警告：以下云端 key 未在启动环境中导出（对应 profile 不可用；云路 fallback 可能空耗超时，OCR 解析将报 Key 未配置）：" | tee -a "$LOG"
  for KEY_ENV in "${MISSING[@]}"; do
    echo "  - $KEY_ENV" | tee -a "$LOG"
  done
  echo "[round27 preflight] 处置：集成人核定 key 值后，在同一终端 export 再执行本脚本。" | tee -a "$LOG"
fi

PYTHONPATH="services/api:." \
WORKBENCH_RUNTIME_DIR="$ISO" \
WORKBENCH_AI_SETTINGS_PATH="$ISO/ai_provider_settings.json" \
WORKBENCH_AI_ROLE_SETTINGS_PATH="$ISO/ai_role_bindings.json" \
WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1 \
WORKBENCH_PROTOCOL_V3_WORKFLOW_DB="$ROOT/runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/protocol_v3_product.sqlite" \
nohup /opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python \
  -m uvicorn app.main:app --host 127.0.0.1 --port 5301 >> "$LOG" 2>&1 &
echo "launched pid $!"
