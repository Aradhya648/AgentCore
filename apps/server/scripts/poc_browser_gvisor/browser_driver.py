"""PoC long-lived browser driver — the sandbox-side of the D9 stdio JSON-RPC channel.

Runs INSIDE the runsc sandbox as a persistent process. It drives ONE Playwright
Chromium (sync API) across many commands and speaks newline-delimited JSON over
stdin/stdout to the host:

    host → driver (stdin):   {"id": <int>, "cmd": "<name>", ...args}\n
    driver → host (stdout):  {"id": <int>, "ok": <bool>, ...result}\n

Only JSON-RPC lines are written to stdout (fd 1); everything else (Playwright /
Chromium chatter) goes to stderr, so the host's line reader never desyncs. This
mirrors the product control channel we validate before writing product code:
one browser, long-lived, one command at a time, screenshots returned as base64.

Env knobs:
- ``BROWSER_PROXY``   e.g. http://10.200.0.1:8888 — forces ALL Chromium egress
  through the host filtering proxy (``--proxy-server``); unset ⇒ direct.
- ``BROWSER_WIDTH``   viewport / keyframe width (default 1280).
- ``BROWSER_JPEG_Q``  keyframe jpeg quality (default 70).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import sys
import traceback

WIDTH = int(os.environ.get("BROWSER_WIDTH", "1280"))
HEIGHT = int(os.environ.get("BROWSER_HEIGHT", "800"))
JPEG_Q = int(os.environ.get("BROWSER_JPEG_Q", "70"))
PROXY = os.environ.get("BROWSER_PROXY", "").strip()

# gVisor / container-safe Chromium flags (see PoC README). --proxy-server pins
# egress to the host filter proxy; the sandbox netns has no other route out.
CHROME_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
if PROXY:
    CHROME_ARGS.append(f"--proxy-server={PROXY}")


def _log(msg: str) -> None:
    """Diagnostics to stderr only — stdout is reserved for JSON-RPC lines."""
    sys.stderr.write(f"[driver] {msg}\n")
    sys.stderr.flush()


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class Driver:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._page = None

    def launch(self, _req: dict) -> dict:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True, args=CHROME_ARGS)
        self._page = self._browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        return {"chromium_version": self._browser.version, "proxy": PROXY or None}

    def navigate(self, req: dict) -> dict:
        url = req["url"]
        resp = self._page.goto(url, wait_until="load", timeout=int(req.get("timeout_ms", 45000)))
        return {
            "http_status": resp.status if resp else None,
            "final_url": self._page.url,
            "title": self._page.title(),
        }

    def snapshot(self, _req: dict) -> dict:
        aria = self._page.locator("body").aria_snapshot()
        return {"aria_len": len(aria or ""), "aria_head": (aria or "")[:400]}

    def screenshot(self, _req: dict) -> dict:
        png = self._page.screenshot(type="jpeg", quality=JPEG_Q)
        return {"bytes": len(png), "b64": base64.b64encode(png).decode("ascii")}

    def click(self, req: dict) -> dict:
        self._page.click(req["selector"], timeout=int(req.get("timeout_ms", 5000)))
        return {"final_url": self._page.url}

    def type(self, req: dict) -> dict:
        self._page.fill(req["selector"], req.get("text", ""), timeout=int(req.get("timeout_ms", 5000)))
        return {"final_url": self._page.url}

    def scroll(self, req: dict) -> dict:
        dy = int(req.get("dy", 600))
        self._page.mouse.wheel(0, dy)
        return {"dy": dy}

    def ping(self, _req: dict) -> dict:
        # Liveness probe — proves the long-lived stdin/stdout channel survives.
        return {"pong": True}

    def netdiag(self, _req: dict) -> dict:
        """What network stack does netstack expose INSIDE the sandbox?"""
        import subprocess

        out: dict[str, str] = {}
        probes = {
            "addr": ["ip", "-o", "addr"],
            "route": ["ip", "route"],
            "resolv": ["cat", "/etc/resolv.conf"],
        }
        for name, cmd in probes.items():
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                out[name] = (p.stdout + p.stderr).strip()
            except Exception as exc:  # noqa: BLE001
                out[name] = f"ERR {type(exc).__name__}: {exc}"
        return out

    def proxy_fetch(self, req: dict) -> dict:
        """HTTP GET through the configured proxy (no Chromium link-local quirks).

        Proves the sandbox → host-proxy → SSRF-decision path for targets Chromium
        refuses to route (e.g. link-local 169.254.169.254 cloud metadata): a blocked
        target comes back as the proxy's 403, a public one as 200.
        """
        import urllib.error
        import urllib.request

        url = req["url"]
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
        )
        try:
            resp = opener.open(url, timeout=float(req.get("timeout_s", 12)))
            return {"status": resp.status}
        except urllib.error.HTTPError as exc:
            return {"status": exc.code}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    def raw_connect(self, req: dict) -> dict:
        """Attempt a RAW TCP connect from inside the sandbox (bypass-egress probe).

        Success to the internet would mean the netstack has a direct route (BAD:
        the SSRF proxy could be bypassed by a raw socket). We expect this to FAIL
        for public targets and SUCCEED only for the proxy address.
        """
        host, port = req["host"], int(req.get("port", 443))
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(float(req.get("timeout_s", 4.0)))
        try:
            s.connect((host, port))
            return {"connected": True}
        except Exception as exc:  # noqa: BLE001 - the failure IS the evidence
            return {"connected": False, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            s.close()

    def close(self, _req: dict) -> dict:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        return {"closed": True}


def main() -> int:
    driver = Driver()
    _emit({"id": 0, "event": "ready", "chrome_args": CHROME_ARGS})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _emit({"id": None, "ok": False, "error": f"bad json: {exc}"})
            continue
        rid = req.get("id")
        cmd = req.get("cmd", "")
        handler = getattr(driver, cmd, None)
        if handler is None or cmd.startswith("_"):
            _emit({"id": rid, "ok": False, "error": f"unknown cmd: {cmd}"})
            continue
        try:
            result = handler(req)
            _emit({"id": rid, "ok": True, **result})
        except Exception as exc:  # noqa: BLE001 - report, never crash the loop
            _log("cmd failed:\n" + traceback.format_exc())
            _emit({"id": rid, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        if cmd == "close":
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
