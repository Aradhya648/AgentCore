"""PoC async screencast driver — the D14 gate's sandbox side.

Runs INSIDE the runsc/gVisor sandbox and answers ONE question the M1 live-frame plan
depends on: does ``playwright.async_api`` + CDP ``Page.startScreencast`` actually work
inside gVisor, and at what frame rate / per-frame size?

It launches one Chromium (async), renders an OFFLINE animated page (so the gate needs
no network — it isolates "does screencast emit frames in gVisor" from egress), starts a
CDP screencast, and for each frame:

    driver → host (stdout): {"event":"screencast_frame","seq":n,"b64":<jpeg base64>}\\n

then ACKs the frame (``Page.screencastFrameAck`` — without the ack Chromium stops after a
few frames, so the ack path IS part of what the gate proves). On completion:

    driver → host (stdout): {"event":"done","frames":N,"seconds":S}\\n

Only JSON lines go to stdout (fd 1); all Playwright/Chromium chatter goes to stderr so the
host's line reader never desyncs — mirroring the product driver's stdio contract. This is a
SELF-CONTAINED script (stdlib + playwright only): it runs where only the ro-bound system
site-packages exist.

Env: DURATION_S, BROWSER_JPEG_Q, BROWSER_WIDTH, BROWSER_HEIGHT, EVERY_NTH_FRAME.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback

WIDTH = int(os.environ.get("BROWSER_WIDTH", "1280"))
HEIGHT = int(os.environ.get("BROWSER_HEIGHT", "800"))
JPEG_Q = int(os.environ.get("BROWSER_JPEG_Q", "60"))
DURATION_S = float(os.environ.get("DURATION_S", "5"))
EVERY_NTH = int(os.environ.get("EVERY_NTH_FRAME", "1"))

CHROME_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]

# A fully-inline animated page: a box orbiting + a per-frame HUD counter, so pixels
# change every rAF tick (screencast only emits on visual change). No external assets,
# so the sandbox needs no network for the gate.
ANIMATED_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;overflow:hidden;background:#0f1020;font-family:sans-serif}
#box{position:absolute;width:180px;height:180px;border-radius:24px;
 background:linear-gradient(45deg,#ff5f6d,#ffc371);box-shadow:0 0 40px #ff5f6d}
#hud{position:absolute;left:24px;top:24px;color:#fff;font-size:44px;font-weight:700}
</style></head><body><div id="box"></div><div id="hud">0</div>
<script>
const box=document.getElementById('box'),hud=document.getElementById('hud');
let n=0;
function tick(t){
  n++;
  const cx=window.innerWidth/2-90, cy=window.innerHeight/2-90;
  const r=Math.min(cx,cy)*0.85, a=t/500;
  box.style.left=(cx+Math.cos(a)*r)+'px';
  box.style.top=(cy+Math.sin(a)*r)+'px';
  box.style.transform='rotate('+(t/5)+'deg)';
  hud.textContent='frame '+n+'  '+new Date().toISOString().slice(11,23);
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);
</script></body></html>"""


def _log(msg: str) -> None:
    sys.stderr.write(f"[screencast-driver] {msg}\n")
    sys.stderr.flush()


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


async def run() -> None:
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True, args=CHROME_ARGS)
    ctx = await browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
    page = await ctx.new_page()
    await page.set_content(ANIMATED_HTML, wait_until="load")

    cdp = await ctx.new_cdp_session(page)
    seq = 0

    async def _ack(session_id) -> None:
        try:
            await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception as exc:  # noqa: BLE001 - late acks after stop are harmless
            _log(f"ack failed: {type(exc).__name__}: {exc}")

    def on_frame(params: dict) -> None:
        nonlocal seq
        seq += 1
        # CDP delivers the frame ALREADY base64-encoded (jpeg). Pass it straight through,
        # exactly like the product driver will (no decode/re-encode on the hot path).
        _emit({"event": "screencast_frame", "seq": seq, "b64": params["data"]})
        asyncio.create_task(_ack(params.get("sessionId")))

    cdp.on("Page.screencastFrame", on_frame)
    await cdp.send(
        "Page.startScreencast",
        {
            "format": "jpeg",
            "quality": JPEG_Q,
            "maxWidth": WIDTH,
            "maxHeight": HEIGHT,
            "everyNthFrame": EVERY_NTH,
        },
    )
    t0 = time.monotonic()
    await asyncio.sleep(DURATION_S)
    with_stop_error = None
    try:
        await cdp.send("Page.stopScreencast")
    except Exception as exc:  # noqa: BLE001 - report but don't mask the frame count
        with_stop_error = f"{type(exc).__name__}: {exc}"
    dt = time.monotonic() - t0
    # Let any in-flight ack/frame drain before we tear the browser down.
    await asyncio.sleep(0.2)
    _emit({"event": "done", "frames": seq, "seconds": round(dt, 3), "stop_error": with_stop_error})
    await browser.close()
    await pw.stop()


def main() -> int:
    _emit({"event": "ready"})
    try:
        asyncio.run(run())
    except Exception:  # noqa: BLE001 - a launch/screencast failure IS the gate evidence
        _log("driver failed:\n" + traceback.format_exc())
        _emit({"event": "error", "error": "screencast driver failed"})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
