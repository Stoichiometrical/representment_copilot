#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="$ROOT/.runtime"
LOGS="$RUNTIME/logs"
BACKEND_PID="$RUNTIME/backend.pid"
FRONTEND_PID="$RUNTIME/frontend.pid"
COMMAND="${1:-status}"

is_running() {
  [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null
}

install_requirements() {
  command -v python3 >/dev/null || { echo "Python 3 is required."; exit 1; }
  command -v npm >/dev/null || { echo "Node.js and npm are required."; exit 1; }
  if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$ROOT/.venv"
  fi
  echo "Checking Python requirements..."
  "$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check --quiet -r "$ROOT/requirements.txt"
  echo "Checking frontend requirements..."
  if [[ ! -f "$ROOT/frontend/node_modules/vite/bin/vite.js" || ! -f "$ROOT/frontend/node_modules/react/package.json" ]]; then
    (cd "$ROOT/frontend" && npm install --silent)
  fi
}

start_app() {
  if is_running "$BACKEND_PID" || is_running "$FRONTEND_PID"; then
    echo "The application is already running. Use './app status'."
    return
  fi
  install_requirements
  mkdir -p "$LOGS"
  (cd "$ROOT" && nohup "$ROOT/.venv/bin/python" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 >"$LOGS/backend.out.log" 2>"$LOGS/backend.err.log" & echo $! >"$BACKEND_PID")
  (cd "$ROOT/frontend" && nohup node "$ROOT/frontend/node_modules/vite/bin/vite.js" --host 127.0.0.1 --port 5173 >"$LOGS/frontend.out.log" 2>"$LOGS/frontend.err.log" & echo $! >"$FRONTEND_PID")
  sleep 2
  is_running "$BACKEND_PID" || { echo "Backend failed. See .runtime/logs/backend.err.log"; exit 1; }
  is_running "$FRONTEND_PID" || { echo "Frontend failed. See .runtime/logs/frontend.err.log"; exit 1; }
  echo "Representment Desk started: http://127.0.0.1:5173"
}

stop_one() {
  local file="$1" name="$2"
  if is_running "$file"; then
    kill "$(cat "$file")" 2>/dev/null || true
    echo "Stopped $name."
  fi
  rm -f "$file"
}

case "$COMMAND" in
  start) start_app ;;
  stop) stop_one "$FRONTEND_PID" frontend; stop_one "$BACKEND_PID" backend ;;
  restart) "$0" stop; "$0" start ;;
  status)
    is_running "$BACKEND_PID" && echo "Backend: running" || echo "Backend: stopped"
    is_running "$FRONTEND_PID" && echo "Frontend: running" || echo "Frontend: stopped"
    ;;
  *) echo "Usage: ./app {start|stop|status|restart}"; exit 2 ;;
esac
