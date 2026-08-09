#!/bin/zsh
set -euo pipefail

ROOT_DIR="${0:A:h:h}"
export VITE_API_PROXY_TARGET="${VITE_API_PROXY_TARGET:-http://127.0.0.1:8911}"

cd "${ROOT_DIR}/frontend"
exec npm run dev -- --host 127.0.0.1 --port 5174
