#!/usr/bin/env bash
# L2 (core): run the SAME browser workload inside a runsc sandbox whose OCI
# config mirrors the product (empty rootfs + ro host binds + tmpfs + limits),
# plus the browser-bundle bind and host networking. Reports RC / wall time /
# peak memory and copies the screenshot out for visual proof.
set -uo pipefail

URL="${POC_URL:-https://example.com}"
PLAT="${POC_PLATFORM:-systrap}"
BROWSERS="${PLAYWRIGHT_BROWSERS_PATH:-/opt/ms-playwright}"
mkdir -p /out

WORK=/work/l2
rm -rf "$WORK"; mkdir -p "$WORK/scratch"
cp /poc/browser_task.py "$WORK/scratch/"
chmod -R 0777 "$WORK/scratch"

echo "=== L2 OCI mounts ==="
python3 /poc/make_oci.py --bundle "$WORK/bundle" --scratch "$WORK/scratch" \
  --net host --mem-mb 2048 --pids 512 --browsers-path "$BROWSERS" --url "$URL" \
  >/dev/null

R=/work/runsc-root-l2
rm -rf "$R"; mkdir -p "$R"
ID="poc-l2-$$"

python3 /poc/memwatch.py --out /tmp/peak_l2.txt & MW=$!
sleep 0.2
START=$(date +%s%3N)
runsc --rootless --platform="$PLAT" --network=host --root="$R" \
  run --bundle "$WORK/bundle" "$ID"
RC=$?
END=$(date +%s%3N)
kill -TERM "$MW" 2>/dev/null || true; wait "$MW" 2>/dev/null || true
runsc --root="$R" delete --force "$ID" >/dev/null 2>&1 || true

echo "=== L2 RESULT ==="
echo "platform=$PLAT"
echo "exit_code=$RC"
echo "wall_ms=$((END - START))"
echo "peak_pss_mb=$(cat /tmp/peak_l2.txt 2>/dev/null || echo NA)"
if cp "$WORK/scratch/"*.png /out/ 2>/dev/null; then
  echo "screenshot_copied=yes"
else
  echo "screenshot_copied=no"
fi
exit "$RC"
