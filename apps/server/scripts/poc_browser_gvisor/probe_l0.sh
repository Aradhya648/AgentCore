#!/usr/bin/env bash
# L0 environment probe: can runsc start a minimal sandbox inside this
# (privileged) container? Tests version, `runsc do`, and a minimal OCI bundle
# that uses the exact product shape (empty rootfs + ro host binds), on both the
# systrap and ptrace platforms. Never aborts early: reports every step's RC.
set -uo pipefail

echo "=== L0.0 runsc version ==="
runsc --version || true

for PLAT in systrap ptrace; do
  echo "=== L0.1 runsc do /bin/true (platform=$PLAT) ==="
  runsc --rootless --platform="$PLAT" --network=none do /bin/true
  echo "do_${PLAT}_rc=$?"
done

for PLAT in systrap ptrace; do
  echo "=== L0.2 minimal OCI bundle run (empty rootfs + ro host binds, platform=$PLAT) ==="
  B="/work/l0-$PLAT"
  R="/work/runsc-root-l0-$PLAT"
  rm -rf "$B" "$R"; mkdir -p "$B" "$R"
  python3 /poc/make_oci.py --minimal --bundle "$B" --net none >/dev/null
  runsc --rootless --platform="$PLAT" --network=none --root="$R" run --bundle "$B" "poc-l0-$PLAT"
  echo "run_${PLAT}_rc=$?"
  runsc --root="$R" delete --force "poc-l0-$PLAT" >/dev/null 2>&1 || true
done

echo "=== L0 DONE ==="
