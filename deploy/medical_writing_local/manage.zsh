#!/bin/zsh
set -euo pipefail

ROOT="/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/workbench"
DEPLOY_DIR="$ROOT/deploy/medical_writing_local"
LOG_DIR="$DEPLOY_DIR/logs"
BACKEND_SESSION="cms-medical-api-8911"
FRONTEND_SESSION="cms-medical-frontend-5174"

mkdir -p "$LOG_DIR"

listener_pid() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -n 1
}

owned_listener() {
  local pid="$1"
  local cwd
  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
  [[ "$cwd" == "$ROOT" || "$cwd" == "$ROOT/frontend" ]]
}

wait_for_url() {
  local url="$1"
  local attempts=120
  while (( attempts > 0 )); do
    if curl --noproxy '*' -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
    (( attempts -= 1 ))
  done
  print -u2 "Timed out waiting for $url"
  return 1
}

stop_port() {
  local port="$1"
  local pid
  pid="$(listener_pid "$port" || true)"
  [[ -n "$pid" ]] || return 0
  if ! owned_listener "$pid"; then
    print -u2 "Refusing to stop unowned listener on port $port (PID $pid)"
    return 1
  fi
  kill -TERM "$pid"
  local attempts=100
  while (( attempts > 0 )) && kill -0 "$pid" 2>/dev/null; do
    sleep 0.1
    (( attempts -= 1 ))
  done
  if kill -0 "$pid" 2>/dev/null; then
    print -u2 "Listener PID $pid on port $port did not stop"
    return 1
  fi
}

start_services() {
  if [[ -n "$(listener_pid 8911 || true)" || -n "$(listener_pid 5174 || true)" ]]; then
    print -u2 "Port 8911 or 5174 is already in use; run status or restart instead."
    return 1
  fi
  local stamp
  stamp="$(date '+%Y%m%d_%H%M%S')"
  local backend_command
  backend_command="exec ${(q)ROOT}/scripts/start_stable_backend.zsh >> ${(q)LOG_DIR}/backend_${stamp}.log 2>&1"
  screen -dmS "$BACKEND_SESSION" /bin/zsh -lc "$backend_command"
  wait_for_url "http://127.0.0.1:8911/api/runtime-readiness"
  local frontend_command
  frontend_command="exec ${(q)ROOT}/scripts/start_stable_frontend.zsh >> ${(q)LOG_DIR}/frontend_${stamp}.log 2>&1"
  screen -dmS "$FRONTEND_SESSION" /bin/zsh -lc "$frontend_command"
  wait_for_url "http://127.0.0.1:5174/runtime-build.json"
  env -u PYTHONPATH python3 "$DEPLOY_DIR/verify_release.py"
}

stop_services() {
  stop_port 5174
  stop_port 8911
}

status_services() {
  print "frontend_pid=$(listener_pid 5174 || true)"
  print "backend_pid=$(listener_pid 8911 || true)"
  print "legacy_8910_pid=$(listener_pid 8910 || true)"
  env -u PYTHONPATH python3 "$DEPLOY_DIR/verify_release.py"
}

case "${1:-status}" in
  start)
    start_services
    ;;
  stop)
    stop_services
    ;;
  restart)
    stop_services
    start_services
    ;;
  verify)
    env -u PYTHONPATH python3 "$DEPLOY_DIR/verify_release.py"
    ;;
  status)
    status_services
    ;;
  *)
    print -u2 "Usage: $0 {start|stop|restart|status|verify}"
    exit 2
    ;;
esac
