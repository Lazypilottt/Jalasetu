#!/usr/bin/env sh
set -eu

# Run the four distributed roles as separate local processes for smoke
# testing: sys1 edge (:3001), sys2/sys3 workers (:3002/:3003), and the sys4
# gateway (:3000). Stop with Ctrl-C. Open http://127.0.0.1:3001 for the built
# frontend served the way production serves it (build it first with
# `cd frontend && npm run build`), or run the Vite dev server with
# VITE_API_BASE_URL=http://127.0.0.1:3000.
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="${PYTHON:-$ROOT_DIR/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python
cd "$ROOT_DIR"

export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}" OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

GATEWAY_PORT="${JALASETU_PORT:-3000}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:$GATEWAY_PORT}" JALASETU_PORT=3001 "$PYTHON" -m distributed.sys1 &
SYS1_PID=$!
JALASETU_PORT=3002 "$PYTHON" -m distributed.sys2 &
SYS2_PID=$!
JALASETU_PORT=3003 "$PYTHON" -m distributed.sys3 &
SYS3_PID=$!

cleanup() {
  kill "$SYS1_PID" "$SYS2_PID" "$SYS3_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

JALASETU_WORKERS="${JALASETU_WORKERS:-sys2=http://127.0.0.1:3002,sys3=http://127.0.0.1:3003}" \
JALASETU_EDGE_URL="${JALASETU_EDGE_URL:-http://127.0.0.1:3001}" \
JALASETU_CORS_ORIGINS="${JALASETU_CORS_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}" \
JALASETU_PORT="$GATEWAY_PORT" \
"$PYTHON" -m distributed.sys4
