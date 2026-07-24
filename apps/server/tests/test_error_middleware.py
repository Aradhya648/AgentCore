"""JSONErrorMiddleware: unhandled errors become JSON 500s that still carry CORS.

Regression guard for the "发送消息显示服务器出错 / CORS" class of bug: a raw
(non-AgentCoreError) exception used to escape as Starlette's outermost bare 500,
which sits *outside* CORSMiddleware and so lacks ``Access-Control-Allow-Origin`` —
the browser then reports a misleading CORS failure and the SPA can only show a
generic error. With JSONErrorMiddleware registered just *inside* CORS, the error
response flows back out through the CORS layer and gets the headers.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from agentcore.middleware.errors import JSONErrorMiddleware

_ORIGIN = "http://localhost:5173"


def _app() -> FastAPI:
    app = FastAPI()
    # Mirror main.py's registration order: JSONError added just before CORS, so
    # CORS ends up the outermost user middleware and wraps JSONError's response.
    app.add_middleware(JSONErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise ValueError("kaboom")  # not an AgentCoreError → unhandled

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_unhandled_error_returns_json_with_cors_headers() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    res = client.get("/boom", headers={"Origin": _ORIGIN})
    assert res.status_code == 500
    assert res.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误，请稍后重试"}
    }
    # The crux: the error response is CORS-visible to the browser.
    assert res.headers.get("access-control-allow-origin") == _ORIGIN


def test_ok_response_is_unaffected() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    res = client.get("/ok", headers={"Origin": _ORIGIN})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert res.headers.get("access-control-allow-origin") == _ORIGIN
