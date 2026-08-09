#!/bin/zsh
set -euo pipefail

ROOT="/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/workbench"
ENV_FILE="${WORKBENCH_AI_ENV_FILE:-$HOME/.config/cms-medical-workbench/ai-runtime.env}"

if [[ ! -r "$ENV_FILE" ]]; then
  print -u2 "Stable backend AI environment is unavailable: $ENV_FILE"
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY is required}"
: "${WORKBENCH_AI_PROVIDER:?WORKBENCH_AI_PROVIDER is required}"
: "${WORKBENCH_AI_MODEL:?WORKBENCH_AI_MODEL is required}"
: "${WORKBENCH_AI_DEPLOYMENT_PROFILE:?WORKBENCH_AI_DEPLOYMENT_PROFILE is required}"
export WORKBENCH_CLIENT_CONTRACT_MODE="${WORKBENCH_CLIENT_CONTRACT_MODE:-enforce}"
export WORKBENCH_MONITORING_AI_PARALLELISM="${WORKBENCH_MONITORING_AI_PARALLELISM:-8}"
# The desktop environment may export Hermes' Python 3.11 site-packages while
# `python3` is the system Python 3.9. Mixing those runtimes crashes uvicorn
# before the application imports.
unset PYTHONPATH

cd "$ROOT"
exec python3 -m uvicorn services.api.app.main:app \
  --app-dir "$ROOT" \
  --host 127.0.0.1 \
  --port 8911
