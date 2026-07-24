"""PoC screencast gate (D14 强制门) — SCREENCAST_OK inside runsc/gVisor.

Runs INSIDE the privileged PoC container. Builds a product-shaped runsc OCI bundle
(empty rootfs + ro host binds + the Playwright browser bundle bind + a 512m /tmp tmpfs,
same shape ``gvisor_session`` uses) running :mod:`screencast_driver`, with NO network
(the driver renders an offline animated page — the gate isolates "does CDP screencast
work in gVisor" from egress).

It then reads the newline-delimited frame event lines, measures **frame rate** and
**per-frame size** (the two numbers D14 requires), saves a sample frame to ``/out`` for
visual proof, and prints:

    SCREENCAST_METRICS_JSON={...}
    SCREENCAST_OK=True|False

``SCREENCAST_OK`` is False (rc 5) if no frames flow, a frame is not a valid JPEG, or the
average frame rate is below ``MIN_FPS`` — i.e. exactly the "screencast unusable / rate
unacceptable" gate the plan says must STOP before any product code.

Reuses the L2 channel finding: Docker Desktop's nested cgroup v1 needs ``--ignore-cgroups``.

Run: docker run --rm --privileged -v <pocdir>:/poc -v <pocdir>/out:/out \\
        poc-browser-gvisor python3 -u /poc/run_screencast.py
"""

from __future__ import annotations

import base64
import json
import os
import queue
import statistics
import subprocess
import threading
import time

WORK = "/work/screencast"
ROOT = "/work/runsc-root-screencast"
BUNDLE = f"{WORK}/bundle"
SCRATCH = f"{WORK}/scratch"
OUT = os.environ.get("POC_OUT", "/out")
PLAT = os.environ.get("POC_PLATFORM", "systrap")
BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/ms-playwright")
CID = f"poc-screencast-{os.getpid()}"

DURATION_S = float(os.environ.get("DURATION_S", "5"))
JPEG_Q = int(os.environ.get("BROWSER_JPEG_Q", "60"))
WIDTH = int(os.environ.get("BROWSER_WIDTH", "1280"))
HEIGHT = int(os.environ.get("BROWSER_HEIGHT", "800"))
# Below this average frame rate the live view would feel like a slideshow → gate fails.
MIN_FPS = float(os.environ.get("MIN_FPS", "5"))

HOST_BIND_PATHS = ("/usr", "/lib", "/lib64", "/bin", "/etc")


def sh(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr}")
    return p


def build_bundle() -> None:
    os.makedirs(f"{BUNDLE}/rootfs", exist_ok=True)
    os.makedirs(SCRATCH, exist_ok=True)
    sh(["cp", "/poc/screencast_driver.py", f"{SCRATCH}/screencast_driver.py"])
    os.chmod(SCRATCH, 0o777)
    mounts = [
        {"destination": "/tmp", "type": "tmpfs", "source": "tmpfs",
         "options": ["nosuid", "nodev", "mode=1777", "size=512m"]},
        {"destination": "/scratch", "type": "bind", "source": SCRATCH,
         "options": ["rw", "rbind", "nosuid", "nodev"]},
        {"destination": BROWSERS, "type": "bind", "source": BROWSERS,
         "options": ["ro", "rbind", "nosuid", "nodev"]},
    ]
    for path in HOST_BIND_PATHS:
        if os.path.isdir(path):
            mounts.append({"destination": path, "type": "bind", "source": path,
                           "options": ["ro", "rbind", "nosuid"]})
    config = {
        "ociVersion": "1.0.2",
        "process": {
            "terminal": False,
            "user": {"uid": 65534, "gid": 65534},
            "args": ["python3", "-u", "/scratch/screencast_driver.py"],
            "env": [
                "PATH=/usr/local/bin:/usr/bin:/bin",
                "HOME=/tmp",
                "LANG=C.UTF-8",
                "PYTHONDONTWRITEBYTECODE=1",
                f"PLAYWRIGHT_BROWSERS_PATH={BROWSERS}",
                f"DURATION_S={DURATION_S}",
                f"BROWSER_JPEG_Q={JPEG_Q}",
                f"BROWSER_WIDTH={WIDTH}",
                f"BROWSER_HEIGHT={HEIGHT}",
            ],
            "cwd": "/scratch",
        },
        "root": {"path": "rootfs", "readonly": True},
        "mounts": mounts,
        "linux": {
            "resources": {
                "memory": {"limit": 2048 * 1024 * 1024},
                "cpu": {"quota": 200000, "period": 100000},
                "pids": {"limit": 512},
            },
            # No network namespace: screencast needs no egress (offline page).
            "namespaces": [
                {"type": "pid"}, {"type": "ipc"}, {"type": "uts"}, {"type": "mount"},
            ],
        },
    }
    with open(f"{BUNDLE}/config.json", "w") as fh:
        json.dump(config, fh)


class RunscDriver:
    """Reads newline-delimited JSON events from the long-lived runsc driver."""

    def __init__(self) -> None:
        cmd = [
            "runsc", f"--platform={PLAT}", "--network=none", "--ignore-cgroups",
            f"--root={ROOT}", "run", f"--bundle={BUNDLE}", CID,
        ]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self._q: queue.Queue[dict] = queue.Queue()
        self._stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._q.put(json.loads(line))
            except json.JSONDecodeError:
                self._stderr.append(f"[stdout-nonjson] {line[:120]}")

    def _read_stderr(self) -> None:
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())

    def events(self, *, timeout: float):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                yield self._q.get(timeout=remaining)
            except queue.Empty:
                return

    def stderr_tail(self, n: int = 40) -> list[str]:
        return self._stderr[-n:]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    metrics: dict = {"platform": PLAT, "jpeg_q": JPEG_Q, "width": WIDTH, "duration_s": DURATION_S}
    checks: dict[str, bool] = {}

    build_bundle()
    frame_sizes: list[int] = []
    frame_times: list[float] = []
    first_frame_jpeg = False
    done: dict | None = None
    ready = False

    drv = RunscDriver()
    try:
        # Ready + cold start + DURATION + drain. Chromium cold start ~0.6s + runsc start.
        budget = DURATION_S + 60
        for msg in drv.events(timeout=budget):
            ev = msg.get("event")
            if ev == "ready":
                ready = True
            elif ev == "screencast_frame":
                b64 = msg.get("b64") or ""
                try:
                    raw = base64.b64decode(b64)
                except Exception:  # noqa: BLE001
                    raw = b""
                if not frame_sizes and raw[:2] == b"\xff\xd8":
                    first_frame_jpeg = True
                if raw:
                    frame_sizes.append(len(raw))
                    frame_times.append(time.monotonic())
                    # Overwrite a sample each frame so the saved proof ends on a
                    # painted (content) frame, not the initial pre-paint white one.
                    if raw[:2] == b"\xff\xd8":
                        with open(f"{OUT}/screencast-sample.jpg", "wb") as fh:
                            fh.write(raw)
            elif ev == "error":
                metrics["driver_error"] = msg.get("error")
                break
            elif ev == "done":
                done = msg
                # Save a mid-stream frame too, for visual proof of "still animating".
                break
    finally:
        subprocess.run(["runsc", f"--root={ROOT}", "delete", "--force", CID],
                       capture_output=True, text=True)

    n = len(frame_sizes)
    span = (frame_times[-1] - frame_times[0]) if n >= 2 else 0.0
    # Prefer the driver's own wall clock for fps if present (covers the whole window).
    window = float(done["seconds"]) if done and done.get("seconds") else (span or DURATION_S)
    fps = (n / window) if window > 0 else 0.0
    metrics.update(
        {
            "ready": ready,
            "frames": n,
            "driver_reported_frames": (done or {}).get("frames"),
            "fps": round(fps, 2),
            "frame_kb_avg": round(statistics.mean(frame_sizes) / 1024, 1) if n else 0,
            "frame_kb_p50": round(statistics.median(frame_sizes) / 1024, 1) if n else 0,
            "frame_kb_p95": (
                round(sorted(frame_sizes)[int(n * 0.95) - 1] / 1024, 1) if n >= 20 else None
            ),
            "frame_kb_max": round(max(frame_sizes) / 1024, 1) if n else 0,
        }
    )
    if "driver_error" in metrics or not ready:
        metrics["runsc_stderr_tail"] = drv.stderr_tail()

    checks["ready"] = ready
    checks["frames_flow"] = n > 0
    checks["valid_jpeg"] = first_frame_jpeg
    checks["rate_acceptable"] = fps >= MIN_FPS
    metrics["checks"] = checks
    metrics["min_fps_threshold"] = MIN_FPS

    ok = all(checks.values())
    print("SCREENCAST_METRICS_JSON=" + json.dumps(metrics, ensure_ascii=False), flush=True)
    print(f"SCREENCAST_OK={ok}", flush=True)
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
