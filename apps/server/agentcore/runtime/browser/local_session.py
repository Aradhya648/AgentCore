"""Local Chromium session via DesktopBrowserBridge (M1 · C1–C4).

Implements :class:`BrowserSession` by POSTing ``/command`` to the desktop Bridge
(Electron main LocalChromiumHost). Never falls back to gVisor (C4): if the Bridge
is unreachable the session reports ``host_unavailable``.

Live screencast (D13/D14): when the Hub attaches viewers it calls
:meth:`start_screencast`, which polls Bridge ``screenshot`` and feeds
``BrowserFrameListener`` (jpeg base64 + width/height). :meth:`stop_screencast`
cancels the poll — zero capture cost when nobody is watching.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agentcore.config import settings
from agentcore.runtime.browser.desktop_bridge import (
    bridge_command_url,
    bridge_request_headers,
    ensure_desktop_bridge_health,
    parse_bridge_error,
)
from agentcore.runtime.browser.navigate_target import rewrite_local_navigate_url
from agentcore.tools.sandbox.browser.protocol import (
    BrowserCommand,
    BrowserCommandResult,
    BrowserDriverCrashedError,
    BrowserFrameListener,
    BrowserSessionError,
    BrowserSessionRequest,
)

# Screencast polls should fail fast; tool commands keep the longer timeout.
_SCREENCAST_POLL_TIMEOUT_S = 5.0


class LocalBridgeSession:
    """One conversation browser tab driven by DesktopBrowserBridge (host_kind=local)."""

    def __init__(
        self,
        *,
        conversation_id: str,
        session_id: str,
        command_timeout_s: float = 60.0,
        screencast_interval_s: float | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.session_id = session_id
        self.created_at = time.time()
        self.last_used = self.created_at
        self._alive = True
        self._timeout = command_timeout_s
        self._frame_listener: BrowserFrameListener | None = None
        self._screencast_task: asyncio.Task[None] | None = None
        self._screencast_interval = (
            float(screencast_interval_s)
            if screencast_interval_s is not None
            else float(settings.browser_local_screencast_interval_seconds)
        )

    @property
    def alive(self) -> bool:
        return self._alive

    def set_frame_listener(self, listener: BrowserFrameListener | None) -> None:
        self._frame_listener = listener

    async def start_screencast(self) -> None:
        """Begin polling Bridge screenshots into the frame listener (viewer-driven)."""
        if not self._alive:
            raise BrowserDriverCrashedError("local bridge session closed")
        if self._screencast_task is not None and not self._screencast_task.done():
            return
        if not ensure_desktop_bridge_health():
            raise BrowserDriverCrashedError(
                "host_unavailable: DesktopBrowserBridge 不可达"
            )
        self._screencast_task = asyncio.create_task(
            self._screencast_loop(), name=f"local-screencast:{self.session_id}"
        )

    async def stop_screencast(self) -> None:
        """Stop the poll loop (idempotent)."""
        task = self._screencast_task
        self._screencast_task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def close(self) -> None:
        self._alive = False
        await self.stop_screencast()
        self._frame_listener = None

    async def send(self, command: BrowserCommand) -> BrowserCommandResult:
        if not self._alive:
            raise BrowserDriverCrashedError("local bridge session closed")
        if not ensure_desktop_bridge_health():
            return BrowserCommandResult(
                ok=False,
                error="host_unavailable: DesktopBrowserBridge 不可达",
                data={},
            )
        self.last_used = time.time()
        args = dict(command.args or {})
        # 甲：相对路径 → workspace://（与用户完整预览同源）；工具层通常已改写，此处纵深。
        if command.action == "navigate":
            raw_url = str(args.get("url") or "").strip()
            rewritten = rewrite_local_navigate_url(raw_url, self.conversation_id)
            if not rewritten:
                return BrowserCommandResult(
                    ok=False,
                    error=(
                        "无效的导航地址：仅支持 http(s) 或本会话工作区相对路径 / workspace://"
                    ),
                    data={},
                )
            args["url"] = rewritten
        payload = {
            "pageId": self.session_id,
            "action": command.action,
            "args": args,
        }
        try:
            raw = await asyncio.to_thread(self._post_command, payload, self._timeout)
        except BrowserSessionError as exc:
            msg = str(exc)
            code = "host_unavailable" if "host_unavailable" in msg else None
            if code:
                return BrowserCommandResult(ok=False, error=msg, data={"code": code})
            raise BrowserDriverCrashedError(msg) from exc

        if not raw.get("ok"):
            err, code = parse_bridge_error(raw, http_status=422)
            data: dict[str, Any] = {}
            if code:
                data["code"] = code
            return BrowserCommandResult(ok=False, error=err, data=data)

        data = dict(raw.get("data") or {})
        frame: bytes | None = None
        frame_b64 = data.pop("frame_b64", None)
        if isinstance(frame_b64, str) and frame_b64:
            try:
                frame = base64.b64decode(frame_b64)
            except Exception:  # noqa: BLE001
                frame = None
        return BrowserCommandResult(ok=True, data=data, frame=frame)

    async def _screencast_loop(self) -> None:
        quality = int(settings.browser_screencast_jpeg_quality)
        interval = max(0.05, self._screencast_interval)
        try:
            while self._alive:
                await self._capture_and_emit(quality=quality)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise

    async def _capture_and_emit(self, *, quality: int) -> None:
        listener = self._frame_listener
        if listener is None or not self._alive:
            return
        if not ensure_desktop_bridge_health():
            return
        payload = {
            "pageId": self.session_id,
            "action": "screenshot",
            "args": {"capture": True, "quality": quality},
        }
        try:
            raw = await asyncio.to_thread(
                self._post_command, payload, _SCREENCAST_POLL_TIMEOUT_S
            )
        except BrowserSessionError:
            return
        except Exception:  # noqa: BLE001 — keep loop alive across transient errors
            return
        if not raw.get("ok"):
            return
        data = dict(raw.get("data") or {})
        frame_b64 = data.get("frame_b64")
        if not isinstance(frame_b64, str) or not frame_b64:
            return
        width = int(data.get("width") or settings.browser_screencast_max_width)
        height = int(data.get("height") or settings.browser_screencast_max_height)
        # Re-read: Hub may have cleared the listener between await and emit.
        listener = self._frame_listener
        if listener is not None:
            listener({"frame_b64": frame_b64, "width": width, "height": height})

    def _post_command(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(
            bridge_command_url(),
            data=body,
            headers=bridge_request_headers(),
            method="POST",
        )
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - loopback
                text = resp.read().decode("utf-8", errors="replace")
                return json.loads(text) if text else {"ok": True, "data": {}}
        except HTTPError as exc:
            try:
                err_body = json.loads(exc.read().decode("utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                err_body = None
            err, code = parse_bridge_error(
                err_body if isinstance(err_body, dict) else None, http_status=exc.code
            )
            if code == "host_unavailable" or exc.code in (401, 503):
                raise BrowserSessionError(f"host_unavailable: {err}") from exc
            return {"ok": False, "error": err, "code": code}
        except (URLError, TimeoutError, OSError) as exc:
            self._alive = False
            raise BrowserSessionError(
                f"host_unavailable: DesktopBrowserBridge 不可达（{type(exc).__name__}）"
            ) from exc


async def open_local_bridge_session(request: BrowserSessionRequest) -> LocalBridgeSession:
    """Factory entry for Registry when ``host_kind=local``."""
    if not ensure_desktop_bridge_health(force=True):
        raise BrowserSessionError(
            "host_unavailable: DesktopBrowserBridge 不可达（未配置或探活失败）"
        )
    sid = (request.session_id or "").strip()
    if not sid:
        # Registry normally assigns session_id before factory; keep a stable fallback.
        import uuid

        sid = uuid.uuid4().hex

    return LocalBridgeSession(
        conversation_id=request.conversation_id,
        session_id=sid,
        command_timeout_s=float(settings.browser_command_timeout_seconds),
    )
