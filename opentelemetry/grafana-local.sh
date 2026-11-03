#!/usr/bin/env bash
# Run Grafana on the laptop against the observability backends on sys1.
#   ./grafana-local.sh up    -> open SSH tunnels + start Grafana on http://localhost:3001
#   ./grafana-local.sh down  -> stop both
# Grafana runs natively when GRAFANA_HOME points at an extracted Grafana release,
# otherwise in Docker. The cluster nodes have 512 MiB cgroups, so Grafana is kept off them.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
STATE="$DIR/.grafana-local"
mkdir -p "$STATE"

case "${1:-up}" in
  up)
    if ! { [ -f "$STATE/tunnel.pid" ] && kill -0 "$(cat "$STATE/tunnel.pid")" 2>/dev/null; }; then
      nohup ssh -N -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
        -L 19090:127.0.0.1:9090 \
        -L 13200:127.0.0.1:3200 \
        -L 13100:127.0.0.1:3100 \
        sys1 >/dev/null 2>&1 &
      echo $! > "$STATE/tunnel.pid"
      sleep 3
    fi
    if [ -n "${GRAFANA_HOME:-}" ]; then
      [ -f "$STATE/grafana.pid" ] && kill "$(cat "$STATE/grafana.pid")" 2>/dev/null || true
      JALASETU_BACKEND_HOST=127.0.0.1 \
      GF_SERVER_HTTP_PORT=3001 \
      GF_PATHS_DATA="$STATE/data" GF_PATHS_LOGS="$STATE/logs" \
      GF_PATHS_PROVISIONING="$DIR/grafana/provisioning" \
      GF_AUTH_ANONYMOUS_ENABLED=true GF_AUTH_ANONYMOUS_ORG_ROLE=Admin \
      GF_AUTH_DISABLE_LOGIN_FORM=true GF_ANALYTICS_REPORTING_ENABLED=false \
      GF_ANALYTICS_CHECK_FOR_UPDATES=false GF_NEWS_NEWS_FEED_ENABLED=false \
      GF_PLUGINS_PREINSTALL_DISABLED=true GF_USERS_DEFAULT_THEME=light \
        nohup "$GRAFANA_HOME/bin/grafana" server --homepath "$GRAFANA_HOME" > "$STATE/grafana.out" 2>&1 &
      echo $! > "$STATE/grafana.pid"
    else
      docker rm -f jalasetu-grafana >/dev/null 2>&1 || true
      docker run -d --name jalasetu-grafana -p 3001:3000 \
        -e JALASETU_BACKEND_HOST=host.docker.internal \
        -e GF_AUTH_ANONYMOUS_ENABLED=true -e GF_AUTH_ANONYMOUS_ORG_ROLE=Admin \
        -e GF_AUTH_DISABLE_LOGIN_FORM=true -e GF_ANALYTICS_REPORTING_ENABLED=false \
        -e GF_NEWS_NEWS_FEED_ENABLED=false -e GF_USERS_DEFAULT_THEME=light \
        -e GF_PATHS_PROVISIONING=/etc/grafana/provisioning \
        -v "$DIR/grafana/provisioning:/etc/grafana/provisioning:ro" \
        grafana/grafana:13.3.0 >/dev/null
    fi
    echo "Grafana: http://localhost:3001"
    ;;
  down)
    if [ -f "$STATE/grafana.pid" ]; then
      kill "$(cat "$STATE/grafana.pid")" 2>/dev/null || true
      rm -f "$STATE/grafana.pid"
    else
      docker rm -f jalasetu-grafana >/dev/null 2>&1 || true
    fi
    [ -f "$STATE/tunnel.pid" ] && kill "$(cat "$STATE/tunnel.pid")" 2>/dev/null || true
    rm -f "$STATE/tunnel.pid"
    ;;
esac
