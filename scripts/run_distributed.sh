#!/usr/bin/env sh
set -eu

# Run the services in separate processes for local smoke testing. Stop with
# Ctrl-C; callers can also run each ``python -m distributed.sysN`` independently.
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="${PYTHON:-$ROOT_DIR/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python

"$PYTHON" -m distributed.sys2 &
SYS2_PID=$!
"$PYTHON" -m distributed.sys3 &
SYS3_PID=$!

cleanup() {
  kill "$SYS2_PID" "$SYS3_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

JALASETU_SYS2_URL="${JALASETU_SYS2_URL:-http://127.0.0.1:3002}" \
JALASETU_SYS3_URL="${JALASETU_SYS3_URL:-http://127.0.0.1:3003}" \
JALASETU_PORT="${JALASETU_PORT:-3000}" \
"$PYTHON" -m distributed.sys4
