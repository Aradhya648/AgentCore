#!/usr/bin/env bash
# L1: run the browser workload directly in the container (no runsc). Establishes
# the baseline (does Playwright+Chromium work at all here) and its memory/timing.
set -uo pipefail

URL="${POC_URL:-https://example.com}"
mkdir -p /out
export POC_OUT=/out POC_SHOT_NAME=screenshot_l1.png POC_URL="$URL"

python3 /poc/memwatch.py --out /tmp/peak_l1.txt & MW=$!
sleep 0.2
START=$(date +%s%3N)
python3 /poc/browser_task.py
RC=$?
END=$(date +%s%3N)
kill -TERM "$MW" 2>/dev/null || true; wait "$MW" 2>/dev/null || true

echo "=== L1 RESULT ==="
echo "exit_code=$RC"
echo "wall_ms=$((END - START))"
echo "peak_pss_mb=$(cat /tmp/peak_l1.txt 2>/dev/null || echo NA)"
exit "$RC"
