"""Smoke-probe the PRODUCT async driver in gVisor (M1 · D14 regression guard).

Unlike ``run_screencast.py`` (which drives a self-contained REFERENCE driver), this runs the
real ``agentcore/tools/sandbox/browser/driver.py`` inside runsc and exercises the async
rewrite end to end WITHOUT network (data: URLs, so no proxy/netns needed):

    ready → start_screencast → (navigate to an animated data: page) → live frames flow
          → stop_screencast → snapshot → screenshot (inline keyframe) → ping → close

It asserts the six-command contract still holds AND that live frames flow concurrently with
commands, then prints PRODUCT_DRIVER_OK. Mount the product browser dir so the driver is
visible:

    docker run --rm --privileged \\
      -v <pocdir>:/poc \\
      -v <repo>/apps/server/agentcore/tools/sandbox/browser:/product_browser:ro \\
      -v <pocdir>/out:/out \\
      poc-browser-gvisor python3 -u /poc/probe_product_driver.py
"""

from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import threading
import time

WORK = "/work/product-driver"
ROOT = "/work/runsc-root-product-driver"
BUNDLE = f"{WORK}/bundle"
SCRATCH = f"{WORK}/scratch"
OUT = os.environ.get("POC_OUT", "/out")
PLAT = os.environ.get("POC_PLATFORM", "systrap")
BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/ms-playwright")
PRODUCT_DRIVER = os.environ.get("PRODUCT_DRIVER", "/product_browser/driver.py")
CID = f"poc-product-driver-{os.getpid()}"

HOST_BIND_PATHS = ("/usr", "/lib", "/lib64", "/bin", "/etc")

ANIMATED = (
    "<!doctype html><html><head><meta charset=utf-8>"
    "<style>html,body{margin:0;height:100%;background:#101827}"
    "#b{position:absolute;width:150px;height:150px;background:#38bdf8;border-radius:20px}</style>"
    "</head><body><div id=b></div><button id=go>Go</button>"
    "<script>const b=document.getElementById('b');let n=0;"
    "function t(x){n++;b.style.left=(Math.cos(x/400)*300+400)+'px';"
    "b.style.top=(Math.sin(x/400)*200+250)+'px';requestAnimationFrame(t);}"
    "requestAnimationFrame(t);</script></body></html>"
)
DATA_URL = "data:text/html;base64," + base64.b64encode(ANIMATED.encode()).decode()


def sh(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr}")
    return p


def build_bundle() -> None:
    os.makedirs(f"{BUNDLE}/rootfs", exist_ok=True)
    os.makedirs(SCRATCH, exist_ok=True)
    sh(["cp", PRODUCT_DRIVER, f"{SCRATCH}/browser_driver.py"])
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
            "args": ["python3", "-u", "/scratch/browser_driver.py"],
            "env": [
                "PATH=/usr/local/bin:/usr/bin:/bin",
                "HOME=/tmp",
                "LANG=C.UTF-8",
                "PYTHONDONTWRITEBYTECODE=1",
                f"PLAYWRIGHT_BROWSERS_PATH={BROWSERS}",
                "BROWSER_WIDTH=1280",
                "BROWSER_HEIGHT=800",
                "BROWSER_JPEG_Q=70",
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
            "namespaces": [
                {"type": "pid"}, {"type": "ipc"}, {"type": "uts"}, {"type": "mount"},
            ],
        },
    }
    with open(f"{BUNDLE}/config.json", "w") as fh:
        json.dump(config, fh)


class RunscChannel:
    """Drives the long-lived product driver over stdio JSON-RPC + collects live frames."""

    def __init__(self) -> None:
        cmd = [
            "runsc", f"--platform={PLAT}", "--network=none", "--ignore-cgroups",
            f"--root={ROOT}", "run", f"--bundle={BUNDLE}", CID,
        ]
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self._replies: queue.Queue[dict] = queue.Queue()
        self.frames: list[dict] = []
        self._stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self._stderr.append(f"[stdout-nonjson] {line[:100]}")
                continue
            if msg.get("event") == "live_frame":
                self.frames.append(msg)
            else:
                self._replies.put(msg)

    def _read_stderr(self) -> None:
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())

    def wait_ready(self, timeout: float = 40.0) -> dict:
        msg = self._replies.get(timeout=timeout)
        if msg.get("event") != "ready":
            raise RuntimeError(f"expected ready, got {msg}")
        return msg

    def rpc(self, cmd: str, *, timeout: float = 60.0, **args: object) -> dict:
        rid = int(time.monotonic() * 1000) % 1_000_000
        self.proc.stdin.write(json.dumps({"id": rid, "cmd": cmd, **args}) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = self._replies.get(timeout=deadline - time.monotonic())
            except queue.Empty:
                break
            if msg.get("id") == rid:
                return msg
        raise TimeoutError(f"rpc {cmd} timed out; stderr:\n" + "\n".join(self._stderr[-20:]))

    def stderr_tail(self, n: int = 40) -> list[str]:
        return self._stderr[-n:]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    build_bundle()
    metrics: dict = {"platform": PLAT}
    checks: dict[str, bool] = {}

    chan: RunscChannel | None = None
    try:
        chan = RunscChannel()
        r = chan.wait_ready(timeout=40)
        checks["ready"] = bool(r.get("ok"))

        r = chan.rpc("start_screencast", quality=60, max_width=1280, max_height=800,
                     every_nth_frame=1, timeout=30)
        checks["start_screencast"] = r.get("ok") and r.get("screencast") == "started"

        r = chan.rpc("navigate", url=DATA_URL, timeout=60)
        metrics["navigate"] = {k: r.get(k) for k in ("ok", "http_status", "final_url")}
        checks["navigate"] = bool(r.get("ok"))

        # Let frames flow concurrently with the (idle) command channel.
        before = len(chan.frames)
        time.sleep(2.0)
        streamed = len(chan.frames) - before
        metrics["frames_during_window"] = streamed
        checks["frames_flow"] = streamed > 0

        # A live frame carries a base64 jpeg + dims.
        if chan.frames:
            f = chan.frames[-1]
            raw = base64.b64decode(f.get("frame_b64") or "")
            metrics["live_frame_kb"] = round(len(raw) / 1024, 1)
            metrics["live_frame_dims"] = [f.get("width"), f.get("height")]
            checks["live_frame_jpeg"] = raw[:2] == b"\xff\xd8"
            with open(f"{OUT}/product-live.jpg", "wb") as fh:
                fh.write(raw)

        r = chan.rpc("stop_screencast", timeout=20)
        checks["stop_screencast"] = r.get("ok") and r.get("screencast") == "stopped"
        after_stop = len(chan.frames)
        time.sleep(0.8)
        metrics["frames_after_stop"] = len(chan.frames) - after_stop
        checks["stop_halts_frames"] = (len(chan.frames) - after_stop) <= 2  # drain slack

        r = chan.rpc("snapshot", timeout=30)
        metrics["snapshot"] = {"ok": r.get("ok"), "version": r.get("snapshot_version"),
                               "has_elements": bool(r.get("elements"))}
        checks["snapshot"] = bool(r.get("ok"))

        r = chan.rpc("screenshot", capture=True, timeout=30)
        raw = base64.b64decode(r.get("frame_b64") or "")
        checks["keyframe_inline_jpeg"] = bool(r.get("ok")) and raw[:2] == b"\xff\xd8"
        metrics["keyframe_kb"] = round(len(raw) / 1024, 1)

        checks["ping"] = bool(chan.rpc("ping", timeout=10).get("ok"))
        checks["close"] = bool(chan.rpc("close", timeout=30).get("ok"))
    except Exception as exc:  # noqa: BLE001 - failure IS the evidence
        import traceback
        metrics["error"] = f"{type(exc).__name__}: {exc}"
        metrics["traceback"] = traceback.format_exc()
        if chan is not None:
            metrics["runsc_stderr_tail"] = chan.stderr_tail()
    finally:
        subprocess.run(["runsc", f"--root={ROOT}", "delete", "--force", CID],
                       capture_output=True, text=True)

    metrics["checks"] = checks
    ok = all(
        checks.get(k, False) for k in (
            "ready", "start_screencast", "navigate", "frames_flow", "live_frame_jpeg",
            "stop_screencast", "stop_halts_frames", "snapshot", "keyframe_inline_jpeg",
            "ping", "close",
        )
    )
    print("PRODUCT_DRIVER_METRICS_JSON=" + json.dumps(metrics, ensure_ascii=False), flush=True)
    print(f"PRODUCT_DRIVER_OK={ok}", flush=True)
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
