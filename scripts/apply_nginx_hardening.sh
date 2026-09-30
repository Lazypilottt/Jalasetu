#!/usr/bin/env bash
# apply_nginx_hardening.sh
# Run on sys4 (as student with sudo) to apply all Nginx optimizations.
# Usage: bash apply_nginx_hardening.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== JalaSetu Nginx Reverse-Proxy Hardening ==="

echo "Step 1: Backing up current configs..."
sudo cp /etc/nginx/sites-available/jalasetu /etc/nginx/sites-available/jalasetu.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true

echo "Step 2: Installing rate-limit and connection-limit shared memory zones..."
sudo cp "$SCRIPT_DIR/nginx_jalasetu_limits.conf" /etc/nginx/conf.d/jalasetu_limits.conf

echo "Step 3: Installing optimized site config..."
sudo cp "$SCRIPT_DIR/nginx_jalasetu_optimized.conf" /etc/nginx/sites-available/jalasetu
sudo ln -sf /etc/nginx/sites-available/jalasetu /etc/nginx/sites-enabled/jalasetu

echo "Step 4: Installing active cluster health prober under supervisord..."
sudo tee /etc/supervisor/conf.d/cluster_health_prober.conf > /dev/null <<EOF
[program:cluster-health-prober]
command=python3 /home/student/Jalasetu/scripts/cluster_health_prober.py
directory=/home/student/Jalasetu
autostart=true
autorestart=true
user=student
stderr_logfile=/var/log/supervisor/cluster_health_prober.err.log
stdout_logfile=/var/log/supervisor/cluster_health_prober.out.log
stopasgroup=true
killasgroup=true
EOF

sudo supervisorctl update

echo "Step 5: Testing nginx syntax..."
sudo nginx -t

echo "Step 6: Reloading the prober and Nginx..."
sudo supervisorctl update
sudo supervisorctl restart cluster-health-prober
sudo nginx -t
sudo nginx -s reload

echo "Step 7: Verifying active endpoints..."
sleep 2
echo -n "Health check: "
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:3204/health
echo -n "SPA Frontend: "
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:3204/
echo -n "Cluster status: "
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:3204/v1/cluster/status

echo "Done! Reverse-proxy layer hardened successfully."
