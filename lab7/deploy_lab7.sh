#!/usr/bin/env bash
# Deploy the Lab 7 proximity search API to sys1-sys4 (ports 8101-8104).
#
#   lab7/deploy_lab7.sh            # all four nodes
#   lab7/deploy_lab7.sh sys2 sys4  # some nodes
#
# Each node gets a fresh ~/lab7 with its own virtualenv, so the service does
# not depend on any other project's environment. A previous ~/lab7 without its
# own virtualenv is moved to ~/lab7.prev-<timestamp>, never deleted. Uses the sys1-sys4 SSH aliases.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NODES=("$@")
[ ${#NODES[@]} -gt 0 ] || NODES=(sys1 sys2 sys3 sys4)

for node in "${NODES[@]}"; do
  port=810${node#sys}
  echo "== $node (port $port)"
  # COPYFILE_DISABLE keeps macOS metadata files out of the archive.
  (cd "$HERE" && COPYFILE_DISABLE=1 tar --no-xattrs -czf - --exclude __pycache__ \
      app/main.py locations.csv link.txt requirements.txt test_api.py lab7-supervisor.conf start_lab7.sh) \
    | ssh -o BatchMode=yes "$node" bash -c "'
        set -euo pipefail
        if [ -d ~/lab7 ] && [ ! -x ~/lab7/venv/bin/uvicorn ]; then
          mv ~/lab7 ~/lab7.prev-\$(date +%Y%m%d%H%M%S)
        fi
        mkdir -p ~/lab7 && tar -xzf - -C ~/lab7 --no-same-owner && rm -f ~/lab7/.uvicorn-*.pgid
        [ -x ~/lab7/venv/bin/python ] || /opt/conda/bin/python3 -m venv ~/lab7/venv
        ~/lab7/venv/bin/pip install -q --no-cache-dir --disable-pip-version-check -r ~/lab7/requirements.txt
        sed \"s/__PORT__/$port/\" ~/lab7/lab7-supervisor.conf | sudo -n tee /etc/supervisor/conf.d/lab7-location-api.conf >/dev/null
        sudo -n supervisorctl reread >/dev/null
        sudo -n supervisorctl update lab7-location-api >/dev/null
        sudo -n supervisorctl restart lab7-location-api
        for i in \$(seq 1 30); do
          if curl -sf -m 3 http://127.0.0.1:$port/health >/dev/null; then echo \"healthy on :$port\"; exit 0; fi
          sleep 1
        done
        echo \"NOT HEALTHY on :$port\" >&2; tail -20 ~/lab7-supervisor.log >&2; exit 1
      '"
done
