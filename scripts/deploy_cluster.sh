#!/usr/bin/env bash
# Rolling deploy of the JalaSetu distributed services to sys1-sys4.
#
#   scripts/deploy_cluster.sh                 # dry run: print what would happen
#   scripts/deploy_cluster.sh --apply         # sync code, install, restart
#   scripts/deploy_cluster.sh --apply --prune # also free disk to fit 1.5 GB/node
#   scripts/deploy_cluster.sh --apply sys2    # only some nodes
#
# Order is sys2, sys3, sys1, sys4: the new workers stay compatible with the old
# gateway, so the gateway is replaced last. Each node gets only what its role
# needs (sys1 has no virtualenv at all). --prune removes the stale
# backend_minimal tree, the .git directory, test output, dev-only packages and
# the pip cache from the remote checkout, plus repository docs and macOS
# "._*" metadata files left by earlier copies. Uses the sys1-sys4 SSH aliases.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REMOTE_DIR=/home/student/Jalasetu
STORAGE_BUDGET_MB=1536
APPLY=0
PRUNE=0
NODES=()
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --prune) PRUNE=1 ;;
    sys[1-4]) NODES+=("$arg") ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
[ ${#NODES[@]} -gt 0 ] || NODES=(sys2 sys3 sys1 sys4)

say() { printf '\n== %s\n' "$*"; }

remote() {  # remote <node> <<'SCRIPT' ... ; scripts are fed over stdin
  local node=$1 script
  script=$(cat)
  if [ "$APPLY" -eq 1 ]; then
    ssh -o BatchMode=yes "$node" bash -s <<<"set -euo pipefail; cd $REMOTE_DIR; $script"
  else
    printf '[dry-run] on %s:\n%s\n' "$node" "$script" | sed 's/^/    /'
  fi
}

sync_paths() {  # sync_paths <node> <path>...
  # tar over ssh: the nodes have no rsync. COPYFILE_DISABLE stops macOS tar
  # from adding "._*" AppleDouble metadata files.
  local node=$1; shift
  local args=(--exclude __pycache__ --exclude '*.pyc' --exclude .DS_Store --exclude '._*')
  if [ "$APPLY" -eq 1 ]; then
    (cd "$ROOT" && COPYFILE_DISABLE=1 tar -czf - "${args[@]}" "$@") \
      | ssh -o BatchMode=yes "$node" "mkdir -p $REMOTE_DIR && tar -xzf - -C $REMOTE_DIR --no-same-owner"
  else
    printf '    [dry-run] tar %s | ssh %s tar -x -C %s/\n' "$*" "$node" "$REMOTE_DIR"
  fi
}

PRUNE_SCRIPT='rm -rf backend_minimal .git output tests .pytest_cache main.docx main.pdf
find . -maxdepth 1 -type f \( -name "*.md" -o -name "*.docx" -o -name "*.pdf" \) -delete
find . -path ./venv -prune -o -name "._*" -type f -print0 | xargs -0 rm -f
if [ -x venv/bin/pip ]; then venv/bin/pip uninstall -y -q matplotlib pytest httpx fastkml lxml fastapi 2>/dev/null || true; fi
python3 -m pip cache purge >/dev/null 2>&1 || true
[ -x venv/bin/pip ] && venv/bin/pip cache purge >/dev/null 2>&1 || true'

FOOTPRINT_SCRIPT="used=\$(du -sm $REMOTE_DIR | cut -f1); cache=\$(du -sm ~/.cache/pip 2>/dev/null | cut -f1 || echo 0)
echo \"footprint: \${used} MB in $REMOTE_DIR (+\${cache:-0} MB pip cache), budget $STORAGE_BUDGET_MB MB\"
[ \"\$used\" -le $STORAGE_BUDGET_MB ] || echo 'WARNING: over the storage budget; rerun with --prune'"

restart_service() {  # restart_service <node>
  remote "$1" <<EOF
sudo -n mkdir -p /var/log/jalasetu
sudo -n cp deploy/supervisor/$1.conf /etc/supervisor/conf.d/jalasetu.conf
sudo -n supervisorctl reread >/dev/null
sudo -n supervisorctl update jalasetu
sudo -n supervisorctl restart jalasetu
EOF
}

wait_healthy() {  # wait_healthy <node> <url>
  remote "$1" <<EOF
for i in \$(seq 1 40); do
  if curl -sf -m 3 $2 >/dev/null; then echo "healthy: $2"; exit 0; fi
  sleep 1
done
echo "NOT HEALTHY after 40s: $2" >&2; exit 1
EOF
}

deploy_worker() {
  local node=$1
  say "$node: stage worker"
  sync_paths "$node" app distributed deploy requirements-runtime.txt
  [ "$PRUNE" -eq 1 ] && remote "$node" <<<"$PRUNE_SCRIPT"
  remote "$node" <<'EOF'
[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/pip install -q --no-cache-dir -r requirements-runtime.txt
EOF
  restart_service "$node"
  wait_healthy "$node" http://127.0.0.1:3000/health
  remote "$node" <<<"$FOOTPRINT_SCRIPT"
}

deploy_edge() {
  say "sys1: edge (frontend, rainfall, infrastructure; standard library only)"
  if [ "$APPLY" -eq 1 ]; then
    (cd "$ROOT/frontend" && VITE_API_BASE_URL="" npm run build --silent)
  else
    echo '    [dry-run] (cd frontend && VITE_API_BASE_URL="" npm run build)'
  fi
  # Replace the built frontend wholesale: tar only adds files, and stale
  # bundles from older builds would otherwise accumulate in dist/assets.
  remote sys1 <<<"rm -rf frontend/dist"
  sync_paths sys1 app/__init__.py app/services/__init__.py app/services/rainfall_service.py app/services/infrastructure.py \
    distributed/__init__.py distributed/capacity.py distributed/sys1.py frontend/dist deploy/supervisor/sys1.conf
  [ "$PRUNE" -eq 1 ] && remote sys1 <<<"$PRUNE_SCRIPT"
  restart_service sys1
  wait_healthy sys1 http://127.0.0.1:3000/health
  remote sys1 <<<"$FOOTPRINT_SCRIPT"
}

deploy_gateway() {
  say "sys4: gateway + Nginx"
  local extra=()
  [ -f "$ROOT/locations - locations.csv" ] && extra+=("locations - locations.csv")
  sync_paths sys4 app distributed deploy scripts runtime requirements-runtime.txt contours_1m.kml "${extra[@]}"
  [ "$PRUNE" -eq 1 ] && remote sys4 <<<"$PRUNE_SCRIPT"
  remote sys4 <<'EOF'
[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/pip install -q --no-cache-dir -r requirements-runtime.txt
EOF
  restart_service sys4
  wait_healthy sys4 http://127.0.0.1:8000/health
  # The prober rewrites runtime/jalasetu_upstream_maps.conf every cycle, so
  # restart it first: an old prober would drop maps the new config needs.
  remote sys4 <<'EOF'
sudo -n supervisorctl restart cluster-health-prober
for i in $(seq 1 30); do grep -q sys1_edge_target runtime/jalasetu_upstream_maps.conf && break; sleep 1; done
sudo -n cp scripts/nginx_jalasetu_limits.conf /etc/nginx/conf.d/jalasetu_limits.conf
sudo -n cp scripts/nginx_jalasetu_optimized.conf /etc/nginx/sites-enabled/jalasetu
sudo -n nginx -t
sudo -n nginx -s reload
curl -sf -m 10 http://127.0.0.1:3000/v1/cluster | head -c 400; echo
EOF
  remote sys4 <<<"$FOOTPRINT_SCRIPT"
}

[ "$APPLY" -eq 1 ] || echo "Dry run. Pass --apply to deploy."
for node in "${NODES[@]}"; do
  case "$node" in
    sys1) deploy_edge ;;
    sys2|sys3) deploy_worker "$node" ;;
    sys4) deploy_gateway ;;
  esac
done
