"""PoC channel validation — the D9/D10 gate before any product code.

Proves the M0 control + egress channel end to end, INSIDE the privileged PoC
container:

1. long-lived runsc container running :mod:`browser_driver` (one Chromium, kept
   alive across many commands);
2. host ↔ sandbox **stdio JSON-RPC** (newline-delimited) survives a multi-command
   session (navigate → snapshot → screenshot → ping → navigate again);
3. **restricted netstack**: the sandbox runs in a dedicated network namespace
   whose ONLY route out is a veth to the host — no NAT, no default internet route;
4. Chromium reaches the public internet ONLY via the host **SSRF filter proxy**
   (``--proxy-server``) on the host end of the veth;
5. **no bypass**: a raw TCP connect from inside the sandbox to a public address
   FAILS (no direct route), while the proxy address is reachable;
6. the proxy **blocks** private / cloud-metadata targets (SSRF at the egress).

Emits ``CHANNEL_METRICS_JSON=...`` and ``CHANNEL_OK=True/False`` and copies the
keyframes to ``/out`` for visual proof. Any architectural failure (netstack →
proxy unreachable, stdio stall) surfaces as CHANNEL_OK=False with the captured
runsc / proxy diagnostics, which is exactly the "stop and report" evidence.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time

NETNS = "sbxpoc"
VETH_H = "vhpoc0"
VETH_S = "vspoc0"
HOST_IP = "10.200.0.1"
SBX_IP = "10.200.0.2"
CIDR = "24"
PROXY_PORT = 8888
PROXY_URL = f"http://{HOST_IP}:{PROXY_PORT}"

WORK = "/work/channel"
ROOT = "/work/runsc-root-channel"
BUNDLE = f"{WORK}/bundle"
SCRATCH = f"{WORK}/scratch"
OUT = os.environ.get("POC_OUT", "/out")
PLAT = os.environ.get("POC_PLATFORM", "systrap")
BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/ms-playwright")
CID = f"poc-channel-{os.getpid()}"

HOST_BIND_PATHS = ("/usr", "/lib", "/lib64", "/bin", "/etc")


def sh(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr}")
    return p


# --- netns + veth: isolated stack whose only route out is the host veth end ---
def net_setup() -> None:
    net_teardown(quiet=True)
    sh(["ip", "netns", "add", NETNS])
    sh(["ip", "link", "add", VETH_H, "type", "veth", "peer", "name", VETH_S])
    sh(["ip", "link", "set", VETH_S, "netns", NETNS])
    sh(["ip", "addr", "add", f"{HOST_IP}/{CIDR}", "dev", VETH_H])
    sh(["ip", "link", "set", VETH_H, "up"])
    sh(["ip", "-n", NETNS, "addr", "add", f"{SBX_IP}/{CIDR}", "dev", VETH_S])
    sh(["ip", "-n", NETNS, "link", "set", VETH_S, "up"])
    sh(["ip", "-n", NETNS, "link", "set", "lo", "up"])
    # Default route via the host veth end. The host does NOT forward/NAT, so this
    # reaches ONLY the proxy (directly connected) — never the internet directly.
    sh(["ip", "-n", NETNS, "route", "add", "default", "via", HOST_IP])


def net_teardown(*, quiet: bool = False) -> None:
    sh(["ip", "netns", "del", NETNS], check=False)
    sh(["ip", "link", "del", VETH_H], check=False)


def build_bundle() -> None:
    os.makedirs(f"{BUNDLE}/rootfs", exist_ok=True)
    os.makedirs(SCRATCH, exist_ok=True)
    sh(["cp", "/poc/browser_driver.py", f"{SCRATCH}/browser_driver.py"])
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
                f"BROWSER_PROXY={PROXY_URL}",
                "BROWSER_WIDTH=1280",
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
            # Reference the persistent veth netns by PATH — the canonical
            # containerd+gVisor way: runsc enters it and netstack CLONES its
            # interfaces + routes (default via the host veth end / proxy).
            "namespaces": [
                {"type": "pid"}, {"type": "ipc"}, {"type": "uts"}, {"type": "mount"},
                {"type": "network", "path": f"/var/run/netns/{NETNS}"},
            ],
        },
    }
    with open(f"{BUNDLE}/config.json", "w") as fh:
        json.dump(config, fh)


class RunscChannel:
    """Drives the long-lived runsc driver over stdio JSON-RPC."""

    def __init__(self) -> None:
        cmd = [
            "runsc", f"--platform={PLAT}", "--network=sandbox", "--ignore-cgroups",
            f"--root={ROOT}", "run", f"--bundle={BUNDLE}", CID,
        ]
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
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
                self._stderr.append(f"[stdout-nonjson] {line}")

    def _read_stderr(self) -> None:
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())

    def wait_ready(self, timeout: float = 30.0) -> dict:
        msg = self._q.get(timeout=timeout)
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
                msg = self._q.get(timeout=deadline - time.monotonic())
            except queue.Empty:
                break
            if msg.get("id") == rid:
                return msg
        raise TimeoutError(f"rpc {cmd} timed out; stderr tail:\n" + "\n".join(self._stderr[-20:]))

    def stderr_tail(self, n: int = 40) -> list[str]:
        return self._stderr[-n:]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    metrics: dict = {"platform": PLAT, "proxy": PROXY_URL, "steps": {}}
    checks: dict[str, bool] = {}

    # The veth host end (10.200.0.1) must exist BEFORE the proxy binds to it.
    net_setup()
    build_bundle()

    # Start the SSRF proxy in the MAIN netns (it has real internet via eth0).
    proxy = subprocess.Popen(
        ["python3", "-u", "/poc/ssrf_proxy.py", "--host", HOST_IP, "--port", str(PROXY_PORT)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    proxy_log: list[str] = []
    threading.Thread(
        target=lambda: [proxy_log.append(ln.rstrip()) for ln in proxy.stdout], daemon=True
    ).start()

    chan: RunscChannel | None = None
    try:
        time.sleep(0.5)  # let the proxy bind
        checks["proxy_ready"] = any("PROXY_READY=" in ln for ln in proxy_log)

        chan = RunscChannel()
        chan.wait_ready(timeout=40)
        checks["ready"] = True

        metrics["netdiag"] = chan.rpc("netdiag", timeout=15)

        r = chan.rpc("launch", timeout=90)
        checks["launch"] = bool(r.get("ok"))
        metrics["chromium_version"] = r.get("chromium_version")

        r = chan.rpc("navigate", url="https://example.com", timeout=90)
        metrics["steps"]["nav1"] = {k: r.get(k) for k in ("ok", "http_status", "title", "final_url")}
        checks["navigate_public_via_proxy"] = r.get("ok") and r.get("http_status") == 200

        r = chan.rpc("snapshot")
        metrics["steps"]["snapshot"] = {"ok": r.get("ok"), "aria_len": r.get("aria_len")}
        checks["snapshot"] = bool(r.get("ok")) and int(r.get("aria_len") or 0) > 0

        r = chan.rpc("screenshot")
        ok_shot = r.get("ok") and int(r.get("bytes") or 0) > 0
        if ok_shot:
            raw = _b64(r["b64"])
            ok_shot = raw[:2] == b"\xff\xd8"  # JPEG SOI
            with open(f"{OUT}/channel-step-1.jpg", "wb") as fh:
                fh.write(raw)
            metrics["steps"]["screenshot"] = {"bytes": r.get("bytes"), "is_jpeg": ok_shot}
        checks["screenshot_jpeg"] = bool(ok_shot)

        # Liveness across time — the stdio channel must survive prior commands.
        checks["ping_liveness"] = bool(chan.rpc("ping").get("ok"))

        r = chan.rpc("navigate", url="https://www.iana.org/domains/reserved", timeout=90)
        metrics["steps"]["nav2"] = {k: r.get(k) for k in ("ok", "http_status", "final_url")}
        checks["second_navigate"] = r.get("ok") and r.get("http_status") == 200

        # No-bypass: raw connect to the proxy succeeds, to the public internet fails.
        rp = chan.rpc("raw_connect", host=HOST_IP, port=PROXY_PORT)
        checks["proxy_reachable"] = bool(rp.get("connected"))
        ri = chan.rpc("raw_connect", host="1.1.1.1", port=443)
        metrics["steps"]["raw_internet"] = ri
        checks["no_direct_egress"] = rp.get("connected") and not ri.get("connected")

        # SSRF: metadata + private targets are refused AT THE PROXY, exercised over
        # the real sandbox → proxy path (proxy_fetch avoids Chromium's link-local
        # bypass). A blocked target returns the proxy's 403.
        meta = chan.rpc("proxy_fetch", url="http://169.254.169.254/latest/meta-data/", timeout=20)
        priv = chan.rpc("proxy_fetch", url="http://10.199.0.9/", timeout=20)
        metrics["steps"]["metadata_via_proxy"] = meta
        metrics["steps"]["private_via_proxy"] = priv

        chan.rpc("close", timeout=30)
    except Exception as exc:  # noqa: BLE001 - failure IS the evidence
        import traceback
        metrics["error"] = f"{type(exc).__name__}: {exc}"
        metrics["traceback"] = traceback.format_exc()
        if chan is not None:
            metrics["runsc_stderr_tail"] = chan.stderr_tail()
    finally:
        time.sleep(0.3)
        proxy.terminate()
        subprocess.run(["runsc", f"--root={ROOT}", "delete", "--force", CID],
                       capture_output=True, text=True)
        net_teardown(quiet=True)

    # SSRF verdicts from the proxy decision log.
    blocked = [ln for ln in proxy_log if '"allowed": false' in ln]
    metrics["proxy_decisions"] = proxy_log[-20:]
    checks["ssrf_metadata_blocked"] = any("169.254.169.254" in ln for ln in blocked)
    checks["ssrf_private_blocked"] = any('"reason": "private_ip"' in ln for ln in blocked)

    metrics["checks"] = checks
    ok = all(checks.get(k, False) for k in (
        "proxy_ready", "ready", "launch", "navigate_public_via_proxy", "snapshot",
        "screenshot_jpeg", "ping_liveness", "second_navigate", "proxy_reachable",
        "no_direct_egress", "ssrf_metadata_blocked", "ssrf_private_blocked",
    ))
    print("CHANNEL_METRICS_JSON=" + json.dumps(metrics, ensure_ascii=False), flush=True)
    print(f"CHANNEL_OK={ok}", flush=True)
    return 0 if ok else 5


def _b64(s: str) -> bytes:
    import base64
    return base64.b64decode(s)


if __name__ == "__main__":
    raise SystemExit(main())
