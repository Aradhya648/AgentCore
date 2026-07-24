"""Whole-container peak memory sampler (cgroup-version agnostic).

Sums Pss (proportional set size) across every process visible in /proc every
100ms and reports the peak. Pss is fair for a browser (many processes sharing
pages) and treats L2 identically: a gVisor-sandboxed Chromium shows up as the
runsc/gofer process footprint, so the same number captures "host RAM cost".

Usage: python memwatch.py --out /tmp/peak.txt   (stop with SIGTERM/SIGINT)
"""

from __future__ import annotations

import glob
import os
import signal
import sys
import time

_running = True


def _stop(*_a) -> None:
    global _running
    _running = False


def _total_pss_kb(self_pid: int) -> int:
    total = 0
    for path in glob.glob("/proc/[0-9]*/smaps_rollup"):
        try:
            pid = int(path.split("/")[2])
        except ValueError:
            continue
        if pid == self_pid:
            continue
        try:
            with open(path) as fh:
                for line in fh:
                    if line.startswith("Pss:"):
                        total += int(line.split()[1])
                        break
        except OSError:
            continue
    return total


def main() -> int:
    out = None
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    self_pid = os.getpid()

    peak_kb = 0
    while _running:
        cur = _total_pss_kb(self_pid)
        if cur > peak_kb:
            peak_kb = cur
        time.sleep(0.1)

    peak_mb = round(peak_kb / 1024, 1)
    print(f"PEAK_PSS_MB={peak_mb}", flush=True)
    if out:
        with open(out, "w") as fh:
            fh.write(str(peak_mb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
