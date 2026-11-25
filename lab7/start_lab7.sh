#!/bin/sh
# Supervisor entry point for the Lab 7 API: start_lab7.sh <port>
#
# If the uvicorn master is killed outright (SIGKILL, OOM), its worker
# processes survive and keep the port, so every restart would fail with
# "address already in use". Before starting, this finds whoever still listens
# on the port and, if it is this service's own leftover workers, stops their
# whole process group and waits for the port to be released.
set -eu
PORT="$1"
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

listener_groups() {
  ss -ltnpH "sport = :$PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u |
    while read -r pid; do ps -o pgid= -p "$pid" 2>/dev/null || true; done | tr -d ' ' | sort -u
}

for group in $(listener_groups); do
  if ps -eo pgid=,args= | awk -v g="$group" '$1 == g' | grep -q "$HERE/venv"; then
    echo "start_lab7: stopping leftover process group $group on port $PORT" >&2
    /bin/kill -s KILL -- "-$group" 2>/dev/null || true
  fi
done

tries=0
while [ "$tries" -lt 20 ] && ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q .; do
  sleep 0.5
  tries=$((tries + 1))
done

# One worker per node by default: each worker holds the dataset (~66 MB), and a
# multi-worker uvicorn adds a ~40 MB manager on these 512 MiB nodes. Nginx
# balances across the four nodes instead. Override with LAB7_WORKERS.
exec "$HERE/venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$PORT" \
  --workers "${LAB7_WORKERS:-1}" --limit-concurrency 64 --backlog 2048 --timeout-keep-alive 5
