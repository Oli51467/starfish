#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_PORT=17327
BACKEND_PORT=14032
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"

FRONTEND_PID=""
BACKEND_PID=""

require_cmd() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 1
  fi
}

cleanup() {
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
    kill "${FRONTEND_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
}

wait_for_url() {
  local url="$1"
  local timeout="${2:-60}"
  local elapsed=0

  while [[ "${elapsed}" -lt "${timeout}" ]]; do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  return 1
}

ensure_port_free() {
  local port="$1"
  local service_name="$2"
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[Starfish] Port ${port} is already in use; cannot start local ${service_name}." >&2
    echo "[Starfish] Please stop the process occupying this port and retry." >&2
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN || true
    exit 1
  fi
}

open_browser() {
  local url="$1"
  if command -v open >/dev/null 2>&1; then
    open "${url}"
    return 0
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${url}" >/dev/null 2>&1 &
    return 0
  fi
  if command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c start "" "${url}" >/dev/null 2>&1 || true
    return 0
  fi
  return 1
}

if [[ ! -d "${BACKEND_DIR}" ]]; then
  echo "Backend directory not found: ${BACKEND_DIR}" >&2
  exit 1
fi

if [[ ! -d "${FRONTEND_DIR}" ]]; then
  echo "Frontend directory not found: ${FRONTEND_DIR}" >&2
  exit 1
fi

require_cmd python3
require_cmd npm
require_cmd curl
require_cmd lsof

if ! python3 -c "import uvicorn" >/dev/null 2>&1; then
  echo "Python package 'uvicorn' is not installed. Run: pip install -r backend/requirements.txt" >&2
  exit 1
fi

trap cleanup EXIT INT TERM

ensure_port_free "${BACKEND_PORT}" "backend"
ensure_port_free "${FRONTEND_PORT}" "frontend"

echo "[Starfish] Starting backend on http://localhost:${BACKEND_PORT}"
(
  cd "${BACKEND_DIR}"
  python3 -m uvicorn main:app --reload --host 0.0.0.0 --port "${BACKEND_PORT}"
) &
BACKEND_PID=$!

echo "[Starfish] Starting frontend on ${FRONTEND_URL}"
(
  cd "${FRONTEND_DIR}"
  npm run dev -- --host 0.0.0.0 --port "${FRONTEND_PORT}" --strictPort
) &
FRONTEND_PID=$!

if wait_for_url "${FRONTEND_URL}" 60; then
  echo "[Starfish] Frontend is ready: ${FRONTEND_URL}"
  if ! open_browser "${FRONTEND_URL}"; then
    echo "[Starfish] Could not auto-open browser. Open manually: ${FRONTEND_URL}"
  fi
else
  echo "[Starfish] Frontend did not become ready in 60s. Check logs above." >&2
fi

echo "[Starfish] Press Ctrl+C to stop both services."
wait "${BACKEND_PID}" "${FRONTEND_PID}"
