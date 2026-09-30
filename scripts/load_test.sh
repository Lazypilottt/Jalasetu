#!/usr/bin/env bash
# load_test.sh — Sends concurrent KML uploads through the gateway and
# monitors memory on sys2/sys3/sys4 throughout.
#
# Usage: bash load_test.sh [KML_FILE] [CONCURRENCY]
# Example: bash load_test.sh contours_1m.kml 4

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

KML_FILE="${1:-$REPO_DIR/contours_1m.kml}"
CONCURRENCY="${2:-4}"
GATEWAY="${GATEWAY:-http://127.0.0.1:3204}"
ENDPOINT="$GATEWAY/analyzeContour"

if [ ! -f "$KML_FILE" ]; then
    echo "ERROR: KML file '$KML_FILE' not found." >&2
    exit 1
fi

echo "=== JalaSetu Hardening Load Test ==="
echo "Target:      $ENDPOINT"
echo "KML file:    $KML_FILE ($(du -sh "$KML_FILE" | cut -f1))"
echo "Concurrency: $CONCURRENCY parallel requests"
echo ""

# ── Memory snapshot function ──────────────────────────────────────────────────
snapshot_mem() {
    local label="$1"
    echo "--- Memory Snapshot @ $label ---"
    for node_info in "sys2:172.17.0.3" "sys3:172.17.0.4" "sys4:172.17.0.5"; do
        local node_name="${node_info%%:*}"
        local node_ip="${node_info##*:}"
        
        local mem_bytes="N/A"
        local uvicorn_rss="N/A"
        
        if [ "$node_ip" = "172.17.0.5" ] || [ "$(hostname)" = "stu1_$node_name" ]; then
            mem_bytes=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null || echo "N/A")
            uvicorn_rss=$(ps -u student -o rss,cmd 2>/dev/null | grep uvicorn | grep -v grep | awk '{print int($1/1024)}' || echo "N/A")
        else
            mem_bytes=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "student@$node_ip" \
                "cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null" 2>/dev/null || echo "N/A")
            uvicorn_rss=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "student@$node_ip" \
                "ps -u student -o rss,cmd 2>/dev/null | grep uvicorn | grep -v grep | awk '{print int(\$1/1024)}'" 2>/dev/null || echo "N/A")
        fi

        if [ "$mem_bytes" != "N/A" ]; then
            local mem_mb=$(echo "$mem_bytes / 1048576" | bc 2>/dev/null || awk "BEGIN {print int($mem_bytes/1048576)}")
            echo "  $node_name ($node_ip): cgroup=${mem_mb}MB / 512MB limit, uvicorn_rss=${uvicorn_rss}MB"
        else
            echo "  $node_name ($node_ip): unreachable"
        fi
    done
    echo ""
}

# ── Baseline ──────────────────────────────────────────────────────────────────
snapshot_mem "BASELINE (IDLE)"

# ── Launch concurrent requests ────────────────────────────────────────────────
echo "Launching $CONCURRENCY concurrent requests to $ENDPOINT..."
RESULTS_DIR=$(mktemp -d)
PIDS=()

for i in $(seq 1 "$CONCURRENCY"); do
    (
        START=$(date +%s%3N)
        HTTP_CODE=$(curl -s -o "$RESULTS_DIR/out_$i.json" \
            -w "%{http_code}" \
            --max-time 120 \
            -F "file=@$KML_FILE" \
            -F "dem_resolution_m=15.0" \
            -F "max_candidate_sites=2" \
            "$ENDPOINT" 2>/dev/null || echo "000")
        END=$(date +%s%3N)
        ELAPSED=$(( END - START ))
        echo "  [Request $i] Finished: HTTP $HTTP_CODE in ${ELAPSED}ms"
    ) &
    PIDS+=($!)
done

# Poll memory while requests are in flight
sleep 2
snapshot_mem "DURING LOAD (+2s)"
sleep 5
snapshot_mem "DURING LOAD (+7s)"

echo "Waiting for all requests to finish..."
for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
done

echo ""
echo "=== Response Breakdown ==="
for i in $(seq 1 "$CONCURRENCY"); do
    if [ -f "$RESULTS_DIR/out_$i.json" ]; then
        CONTENT=$(head -c 200 "$RESULTS_DIR/out_$i.json" 2>/dev/null || echo "")
        echo "  Request $i body preview: $CONTENT"
    fi
done
echo ""

snapshot_mem "POST-LOAD (RECOVERY)"

# ── OOM Check ─────────────────────────────────────────────────────────────────
echo "=== OOM Check Across Cluster ==="
for node_info in "sys2:172.17.0.3" "sys3:172.17.0.4" "sys4:172.17.0.5"; do
    node_name="${node_info%%:*}"
    node_ip="${node_info##*:}"
    if [ "$node_ip" = "172.17.0.5" ] || [ "$(hostname)" = "stu1_$node_name" ]; then
        oom_count=$(sudo dmesg 2>/dev/null | grep -ci 'oom-kill' || echo 0)
    else
        oom_count=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "student@$node_ip" \
            "sudo dmesg 2>/dev/null | grep -ci 'oom-kill' || echo 0" 2>/dev/null || echo "N/A")
    fi
    echo "  $node_name ($node_ip) OOM kills: $oom_count"
done

echo ""
echo "=== Live Cluster Health Prober State ==="
curl -s http://127.0.0.1:3204/v1/cluster/status 2>/dev/null || echo "(cluster status unavailable)"

rm -rf "$RESULTS_DIR"
echo ""
echo "Load test complete."
