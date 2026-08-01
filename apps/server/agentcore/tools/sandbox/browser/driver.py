"""In-sandbox browser driver — the sandbox side of the D9 stdio JSON-RPC channel.

Runs INSIDE the runsc sandbox as a persistent process (staged into the session scratch by
``gvisor_session``). It drives ONE Playwright Chromium and speaks newline-delimited JSON
over stdin/stdout:

    host → driver (stdin):   {"id": <int>, "cmd": "<action>", ...args}\\n
    driver → host (stdout):  {"id": <int>, "ok": <bool>, ...data, "frame_b64"?}\\n

M1 (D14) makes it **async** (``playwright.async_api`` + ``asyncio``) so a CDP
``Page.startScreencast`` can push live frames CONCURRENTLY with command handling. Live
frames ride the same stdout as driver-INITIATED event lines (no request id):

    driver → host (stdout):  {"event": "live_frame", "frame_b64": <b64>, "width", "height"}\\n

The gVisor screencast gate (scripts/poc_browser_gvisor/run_screencast.py) proved this path
(~57fps @ ~14KB/frame @ q60/1280). The M0 six-command semantics, the ``ready`` handshake,
inline ``frame_b64`` keyframe replies and the 8MB line limit are all unchanged.

CRITICAL: only JSON lines go to stdout (fd 1); all Playwright/Chromium chatter goes to
stderr so the host's reader never desyncs. Frames are emitted from the CDP callback with a
single atomic write (no ``await`` between write and flush), so a live frame can never
interleave with a command reply. This file is a SELF-CONTAINED script (stdlib + playwright
only — NO agentcore imports): it executes where only the ro-bound system site-packages exist.

Egress is pinned to the host SSRF proxy via ``BROWSER_PROXY`` (--proxy-server); the sandbox
netns has no other route out, so there is no bypass.

Env: BROWSER_PROXY, BROWSER_WIDTH, BROWSER_HEIGHT, BROWSER_JPEG_Q.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import traceback

WIDTH = int(os.environ.get("BROWSER_WIDTH", "1280"))
HEIGHT = int(os.environ.get("BROWSER_HEIGHT", "800"))
JPEG_Q = int(os.environ.get("BROWSER_JPEG_Q", "70"))
PROXY = os.environ.get("BROWSER_PROXY", "").strip()

CHROME_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
if PROXY:
    CHROME_ARGS.append(f"--proxy-server={PROXY}")

# The commands the host may invoke (allowlist keeps ``cmd:"start"`` / dunder probing from
# reaching internal methods). ``input`` (M2 · D17) injects user takeover events via CDP Input.
_COMMANDS = frozenset(
    {
        "navigate", "click", "type", "scroll", "snapshot", "screenshot",
        "set_content", "set_viewport",
        "ping", "start_screencast", "stop_screencast", "input", "close",
    }
)

# CDP Input event-type maps (M2 接管注入): our compact wire verbs → CDP domain verbs.
_MOUSE_TYPES = {
    "down": "mousePressed",
    "up": "mouseReleased",
    "move": "mouseMoved",
    "wheel": "mouseWheel",
}
_KEY_TYPES = {"down": "keyDown", "up": "keyUp"}
# CDP dispatchKeyEvent modifier bitmask (Alt=1, Ctrl=2, Meta=4, Shift=8).
_MODIFIER_BITS = {
    "alt": 1, "control": 2, "ctrl": 2, "meta": 4, "cmd": 4, "command": 4, "shift": 8,
}


def _modifier_bitmask(mods) -> int:
    """Accept an int bitmask or a list of modifier names → CDP modifier bitmask."""
    if isinstance(mods, bool):  # bool is an int subclass — reject the accidental True/False
        return 0
    if isinstance(mods, int):
        return mods
    if not mods:
        return 0
    bits = 0
    for name in mods:
        bits |= _MODIFIER_BITS.get(str(name).lower(), 0)
    return bits

# Interactive-element selector for the ref-annotated snapshot (click/type targets).
# Password fields are labeled role=password; their ``value`` is NEVER included in name
# (AI must never see or type passwords — login goes through user takeover).
_SNAPSHOT_JS = r"""
(version) => {
  const sel = [
    'a', 'button', 'input', 'textarea', 'select',
    '[role=button]', '[role=link]', '[role=textbox]', '[role=checkbox]',
    '[role=tab]', '[role=menuitem]', '[onclick]'
  ].join(',');
  const out = [];
  let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    n++;
    const ref = 'e' + n;
    el.setAttribute('data-acref', ref);
    const type = (el.getAttribute('type') || '').toLowerCase();
    const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
    const isPassword = type === 'password' || ac.includes('password');
    const role = isPassword ? 'password' : (el.getAttribute('role') || el.tagName.toLowerCase());
    // Password: never leak value into the snapshot name (DOM-as-source-of-truth).
    const nameSrc = isPassword
      ? (el.getAttribute('aria-label') || el.getAttribute('placeholder') || '')
      : (el.getAttribute('aria-label') || el.textContent
        || el.getAttribute('placeholder') || el.value || '');
    let name = nameSrc.trim().replace(/\s+/g, ' ').slice(0, 100);
    out.push(`[${ref}] ${role}${name ? ': ' + name : ''}`);
    if (n >= 200) break;
  }
  return out.join('\n');
}
"""

# Evaluated on the resolved element before fill — DOM type/autocomplete is authoritative.
_IS_PASSWORD_JS = r"""
(el) => {
  const type = (el.getAttribute('type') || '').toLowerCase();
  const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
  return type === 'password' || ac.includes('password');
}
"""


def _log(msg: str) -> None:
    sys.stderr.write(f"[browser-driver] {msg}\n")
    sys.stderr.flush()


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class Driver:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._snapshot_version = 0
        self._cdp = None
        self._screencast_on = False
        # Last screencast frame's device dims — the coordinate space the host's takeover
        # events live in (帧像素空间). Used to rescale input to the viewport (M2).
        self._last_frame_w = WIDTH
        self._last_frame_h = HEIGHT

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True, args=CHROME_ARGS)
        self._ctx = await self._browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
        self._page = await self._ctx.new_page()

    # -- helpers ---------------------------------------------------------------
    async def _keyframe_b64(self) -> str:
        png = await self._page.screenshot(type="jpeg", quality=JPEG_Q)
        return base64.b64encode(png).decode("ascii")

    async def _page_state(self, *, capture: bool) -> dict:
        state = {"final_url": self._page.url, "title": await self._page.title()}
        if capture:
            state["frame_b64"] = await self._keyframe_b64()
        # Any page mutation invalidates prior snapshot refs (防错点).
        # Return the bumped version so the model can align the next ref call
        # without a forced re-snapshot (refs themselves still need snapshot).
        self._snapshot_version += 1
        state["snapshot_version"] = self._snapshot_version
        return state

    def _resolve_ref(self, req: dict):
        ref = req.get("ref")
        version = req.get("snapshot_version")
        if not ref:
            raise ValueError("缺少 ref（先调用 browser_snapshot 获取元素 ref）")
        if version is not None and int(version) != self._snapshot_version:
            raise ValueError(
                f"ref 版本过期（快照 v{version} ≠ 当前 v{self._snapshot_version}）：页面已变化，"
                "请重新 browser_snapshot 获取最新 ref"
            )
        return self._page.locator(f'[data-acref="{ref}"]')

    # -- commands --------------------------------------------------------------
    async def navigate(self, req: dict) -> dict:
        resp = await self._page.goto(
            req["url"], wait_until="load", timeout=int(req.get("timeout_ms", 45000))
        )
        state = await self._page_state(capture=bool(req.get("capture", True)))
        state["http_status"] = resp.status if resp else None
        return state

    async def click(self, req: dict) -> dict:
        await self._resolve_ref(req).click(timeout=int(req.get("timeout_ms", 8000)))
        return await self._page_state(capture=bool(req.get("capture", True)))

    async def type(self, req: dict) -> dict:
        loc = self._resolve_ref(req)
        # Hard-reject password fields (DOM-authoritative). Host maps ``password_blocked``
        # in the error string to a machine-readable ToolResult; never fill.
        if await loc.evaluate(_IS_PASSWORD_JS):
            raise ValueError(
                "password_blocked: AI 不得填写密码框；"
                "请 escalate(blocking=true, browser_login=true) 让用户接管登录"
            )
        await loc.fill(req.get("text", ""), timeout=int(req.get("timeout_ms", 8000)))
        return await self._page_state(capture=bool(req.get("capture", True)))

    async def scroll(self, req: dict) -> dict:
        await self._page.mouse.wheel(0, int(req.get("dy", 600)))
        await self._page.wait_for_timeout(200)
        return await self._page_state(capture=bool(req.get("capture", True)))

    async def snapshot(self, _req: dict) -> dict:
        self._snapshot_version += 1
        tree = await self._page.evaluate(_SNAPSHOT_JS, self._snapshot_version)
        try:
            aria = await self._page.locator("body").aria_snapshot()
        except Exception:  # noqa: BLE001 - aria snapshot is best-effort context
            aria = ""
        return {
            "final_url": self._page.url,
            "title": await self._page.title(),
            "snapshot_version": self._snapshot_version,
            "elements": tree,
            "aria": (aria or "")[:6000],
        }

    async def screenshot(self, req: dict) -> dict:
        state = {"final_url": self._page.url, "title": await self._page.title()}
        if req.get("capture", True):
            state["frame_b64"] = await self._keyframe_b64()
        return state

    async def set_viewport(self, req: dict) -> dict:
        """Host-only: resize viewport for multi-breakpoint self-test (P1c critic)."""
        w = int(req.get("width") or WIDTH)
        h = int(req.get("height") or HEIGHT)
        await self._page.set_viewport_size({"width": w, "height": h})
        return await self._page_state(capture=bool(req.get("capture", False)))

    async def set_content(self, req: dict) -> dict:
        """Host-only: load assembled HTML (workspace preview) without a URL."""
        html = req.get("html") or ""
        await self._page.set_content(
            str(html),
            wait_until="load",
            timeout=int(req.get("timeout_ms", 45000)),
        )
        return await self._page_state(capture=bool(req.get("capture", False)))

    async def ping(self, _req: dict) -> dict:
        return {"pong": True}

    # -- CDP session (shared by screencast + input) ---------------------------
    async def _ensure_cdp(self):
        """Lazily open the page's CDP session (once), wiring the screencast frame sink."""
        if self._cdp is None:
            self._cdp = await self._ctx.new_cdp_session(self._page)
            self._cdp.on("Page.screencastFrame", self._on_screencast_frame)
        return self._cdp

    # -- live screencast (M1 · D14) -------------------------------------------
    async def start_screencast(self, req: dict) -> dict:
        """Begin CDP screencast; frames flow as ``live_frame`` event lines until stop."""
        if self._screencast_on:
            return {"screencast": "already_on"}
        await self._ensure_cdp()
        await self._cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": int(req.get("quality", 60)),
                "maxWidth": int(req.get("max_width", WIDTH)),
                "maxHeight": int(req.get("max_height", HEIGHT)),
                "everyNthFrame": max(1, int(req.get("every_nth_frame", 1))),
            },
        )
        self._screencast_on = True
        return {"screencast": "started"}

    async def stop_screencast(self, _req: dict) -> dict:
        if not self._screencast_on:
            return {"screencast": "already_off"}
        try:
            if self._cdp is not None:
                await self._cdp.send("Page.stopScreencast")
        finally:
            self._screencast_on = False
        return {"screencast": "stopped"}

    def _on_screencast_frame(self, params: dict) -> None:
        # CDP delivers the frame ALREADY base64-encoded (jpeg): pass it straight through
        # (no host decode/re-encode). One atomic write ⇒ never interleaves a command reply.
        md = params.get("metadata") or {}
        w = int(md.get("deviceWidth") or WIDTH)
        h = int(md.get("deviceHeight") or HEIGHT)
        # Remember the frame's dims: takeover input coordinates are in this space (M2).
        self._last_frame_w = w or WIDTH
        self._last_frame_h = h or HEIGHT
        _emit(
            {
                "event": "live_frame",
                "frame_b64": params.get("data", ""),
                "width": w,
                "height": h,
            }
        )
        # Ack is REQUIRED or Chromium stops after a few frames; it also IS the backpressure
        # knob (we ack after emitting, so a blocked stdout throttles production).
        asyncio.create_task(self._ack(params.get("sessionId")))

    async def _ack(self, session_id) -> None:
        try:
            if self._cdp is not None:
                await self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception as exc:  # noqa: BLE001 - late acks after stop/close are harmless
            _log(f"screencast ack failed: {type(exc).__name__}: {exc}")

    # -- user takeover input injection (M2 · D17) -----------------------------
    async def input(self, req: dict) -> dict:
        """Inject a batch of takeover events via the CDP Input domain.

        Coordinates arrive in frame-pixel space (``browser_live_frame`` dims) and are
        rescaled to the viewport here. Events dispatch in order; a bad single event is
        skipped (never fails the batch). CRITICAL: key/text CONTENT is never logged (D17 —
        it may be a password); only counts/kinds are observable.
        """
        cdp = await self._ensure_cdp()
        events = req.get("events") or []
        fw = float(req.get("frame_width") or self._last_frame_w or WIDTH)
        fh = float(req.get("frame_height") or self._last_frame_h or HEIGHT)
        sx = (WIDTH / fw) if fw else 1.0
        sy = (HEIGHT / fh) if fh else 1.0
        injected = 0
        for ev in events:
            kind = ev.get("kind")
            try:
                if kind == "mouse":
                    ok = await self._inject_mouse(cdp, ev, sx, sy)
                elif kind == "key":
                    ok = await self._inject_key(cdp, ev)
                elif kind == "text":
                    await cdp.send("Input.insertText", {"text": str(ev.get("text") or "")})
                    ok = True
                else:
                    ok = False
            except Exception as exc:  # noqa: BLE001 - skip a bad event; NEVER log its content
                _log(f"input event skipped (kind={kind}): {type(exc).__name__}")
                ok = False
            if ok:
                injected += 1
        return {"injected": injected}

    async def _inject_mouse(self, cdp, ev: dict, sx: float, sy: float) -> bool:
        cdp_type = _MOUSE_TYPES.get(str(ev.get("type")))
        if cdp_type is None:
            return False
        params: dict = {
            "type": cdp_type,
            "x": float(ev.get("x") or 0) * sx,
            "y": float(ev.get("y") or 0) * sy,
        }
        button = ev.get("button")
        if cdp_type in ("mousePressed", "mouseReleased"):
            params["button"] = str(button or "left")
            params["clickCount"] = int(ev.get("click_count") or 1)
        elif cdp_type == "mouseMoved":
            if button:
                params["button"] = str(button)
        elif cdp_type == "mouseWheel":
            params["deltaX"] = float(ev.get("delta_x") or 0)
            params["deltaY"] = float(ev.get("delta_y") or 0)
        await cdp.send("Input.dispatchMouseEvent", params)
        return True

    async def _inject_key(self, cdp, ev: dict) -> bool:
        cdp_type = _KEY_TYPES.get(str(ev.get("type")))
        if cdp_type is None:
            return False
        params: dict = {"type": cdp_type, "key": str(ev.get("key") or "")}
        code = ev.get("code")
        if code:
            params["code"] = str(code)
        mods = _modifier_bitmask(ev.get("modifiers"))
        if mods:
            params["modifiers"] = mods
        await cdp.send("Input.dispatchKeyEvent", params)
        return True

    async def close(self, _req: dict) -> dict:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        return {"closed": True}


async def _stdin_reader() -> asyncio.StreamReader:
    """Async line reader over fd 0 (Linux sandbox) so stdin + screencast run concurrently."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader(limit=1024 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    return reader


async def _run() -> int:
    driver = Driver()
    try:
        await driver.start()
    except Exception:  # noqa: BLE001 - launch failure must reach the host
        _log("launch failed:\n" + traceback.format_exc())
        _emit({"id": 0, "event": "ready", "ok": False, "error": "browser launch failed"})
        return 2
    _emit({"id": 0, "event": "ready", "ok": True})

    reader = await _stdin_reader()
    while True:
        raw = await reader.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _emit({"id": None, "ok": False, "error": f"bad json: {exc}"})
            continue
        rid = req.get("id")
        cmd = req.get("cmd", "")
        if cmd not in _COMMANDS:
            _emit({"id": rid, "ok": False, "error": f"unknown cmd: {cmd}"})
            continue
        handler = getattr(driver, cmd)
        try:
            result = await handler(req)
            _emit({"id": rid, "ok": True, **result})
        except Exception as exc:  # noqa: BLE001 - report, never crash the loop
            _log(f"cmd {cmd} failed:\n" + traceback.format_exc())
            _emit({"id": rid, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        if cmd == "close":
            break
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001 - a fatal loop error must be visible on stderr
        _log("fatal:\n" + traceback.format_exc())
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
