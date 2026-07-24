"""Return unhandled errors as JSON *inside* the CORS layer.

FastAPI's built-in 500 fallback lives on Starlette's ``ServerErrorMiddleware``,
which is the *outermost* middleware — outside ``CORSMiddleware``. So any exception
that is not an :class:`~agentcore.core.errors.AgentCoreError` (e.g. a raw
SQLAlchemy ``ProgrammingError``) escapes as a bare 500 with **no**
``Access-Control-Allow-Origin`` header. The browser then reports it as a confusing
CORS failure and the SPA can only show a generic "network/server error" — the real
cause is invisible client-side.

This pure-ASGI middleware is registered *inside* ``CORSMiddleware`` (added just
before it in ``main.py``), so the JSON error response it emits flows back out
through the CORS layer and picks up the CORS headers — the browser then receives a
readable ``{"error": {"code", "message"}}`` body (the same contract the SPA already
understands for :class:`AgentCoreError`).

It only substitutes a response when the response has **not** started yet. A
streaming turn (SSE) that fails mid-flight has already flushed its ``200`` +
CORS headers, so we re-raise and let the stream tear down exactly as before.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agentcore.core.logging import get_logger

logger = get_logger(__name__)


class JSONErrorMiddleware:
    """Catch unhandled exceptions and emit a CORS-friendly JSON 500."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            method = scope.get("method", "?")
            path = scope.get("path", "?")
            logger.exception("http.unhandled_error", method=method, path=path)
            # Headers already flushed (e.g. a live SSE turn) — we can no longer
            # swap the response, so let it propagate and tear the stream down.
            if response_started:
                raise
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务器内部错误，请稍后重试",
                    }
                },
            )
            await response(scope, receive, send)
