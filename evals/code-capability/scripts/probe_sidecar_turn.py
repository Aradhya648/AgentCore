"""Drive one Desktop-equivalent sidecar turn against a local workspace root.

Mirrors apps/desktop main-process spawn + stdio JSON-RPC (initialize / startTurn /
respond), without Electron UI clicks. Used by code-capability S2-style evals.

From repo root or apps/server::

    uv run python ../../evals/code-capability/scripts/probe_sidecar_turn.py \\
      --workspace <abs-or-rel> --prompt-file <PROMPT.md> --title code-cap-S2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = REPO_ROOT / "apps" / "server"
DEFAULT_BASE = os.environ.get("PROBE_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_USER = os.environ.get("DEV_USERNAME", "dev")
DEFAULT_PASS = os.environ.get("DEV_PASSWORD", "devpassword")
OUT_DIR = REPO_ROOT / "logs" / "probes"


def _venv_python() -> Path:
    win = SERVER_DIR / ".venv" / "Scripts" / "python.exe"
    unix = SERVER_DIR / ".venv" / "bin" / "python"
    if win.exists():
        return win
    if unix.exists():
        return unix
    raise SystemExit(f"no server venv python under {SERVER_DIR}")


class SidecarRpc:
    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._reader_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    async def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, self.proc.stdout.readline)
            if line == "":
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(RuntimeError("sidecar stdout closed"))
                self._pending.clear()
                return
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"[sidecar stderr-ish] {line[:200]}", flush=True)
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                rid = msg["id"]
                fut = self._pending.pop(rid, None)
                if fut is None:
                    continue
                if "error" in msg:
                    err = msg["error"] or {}
                    fut.set_exception(
                        RuntimeError(f"RPC error {err.get('code')}: {err.get('message')}")
                    )
                else:
                    fut.set_result(msg.get("result"))
            elif "method" in msg:
                await self._notifications.put(msg)

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        rid = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[rid] = fut
        line = json.dumps(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        return await fut

    async def notify_drain(self) -> dict[str, Any]:
        return await self._notifications.get()


import contextlib  # noqa: E402  — kept after class for readability of main flow


async def _login(client: httpx.AsyncClient, user: str, password: str) -> str:
    r = await client.post(
        "/v1/auth/token", json={"username": user, "password": password}
    )
    r.raise_for_status()
    return str(r.json()["access_token"])


async def _mint_inference(client: httpx.AsyncClient, base_url: str) -> dict[str, str]:
    r = await client.post("/v1/inference/token")
    r.raise_for_status()
    body = r.json()
    return {
        "baseUrl": f"{base_url.rstrip('/')}/v1/inference/v1",
        "apiKey": str(body["token"]),
        "model": str(body["model"]),
    }


def _ensure_fs_root(workspace: Path) -> str:
    """Append/reuse an entry in Desktop userData fs-roots.json; return root id."""
    roots_path = (
        Path(os.environ.get("APPDATA", "")) / "agentcore-desktop" / "fs-roots.json"
    )
    root_id = str(uuid.uuid4())
    abs_path = str(workspace.resolve())
    rows: list[dict[str, Any]] = []
    if roots_path.exists():
        rows = json.loads(roots_path.read_text(encoding="utf-8"))
        for row in rows:
            if str(row.get("absPath", "")).lower() == abs_path.lower():
                return str(row["id"])
    rows.append({"id": root_id, "name": workspace.name, "absPath": abs_path})
    roots_path.parent.mkdir(parents=True, exist_ok=True)
    roots_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"[fs-roots] registered {root_id} -> {abs_path}", flush=True)
    return root_id


async def _auto_respond(
    rpc: SidecarRpc, conversation_id: str, ev_type: str, payload: dict[str, Any]
) -> None:
    """Settle hot-path cards so an unattended eval can finish."""
    if ev_type == "approval_required":
        aid = payload.get("approval_id")
        if not aid:
            return
        print(f"[auto] approve_always tool={payload.get('tool_name')}", flush=True)
        await rpc.request(
            "respond",
            {
                "requestId": aid,
                "conversationId": conversation_id,
                "result": {"kind": "approval", "decision": "approve_always"},
            },
        )
    elif ev_type == "delegation_authorization_required":
        auth_id = payload.get("authorization_id")
        if not auth_id:
            return
        print("[auto] grant_delegation", flush=True)
        await rpc.request(
            "respond",
            {
                "requestId": auth_id,
                "conversationId": conversation_id,
                "result": {
                    "kind": "delegation_authorization",
                    "decision": "grant_delegation",
                },
            },
        )


async def run(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace not a directory: {workspace}")
    prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not prompt:
        raise SystemExit("empty prompt")

    root_id = _ensure_fs_root(workspace)
    data_dir = (
        Path(os.environ.get("APPDATA", str(REPO_ROOT / "logs")))
        / "agentcore-desktop"
        / "sidecar"
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    conversation_id = ""
    trace_id = uuid.uuid4().hex
    turn_id = str(uuid.uuid4())
    user_message_id = str(uuid.uuid4())
    events: list[dict[str, Any]] = []

    async with httpx.AsyncClient(base_url=args.base_url, timeout=60.0) as client:
        token = await _login(client, args.user, args.password)
        client.headers["Authorization"] = f"Bearer {token}"
        me = (await client.get("/v1/auth/me")).json()
        user_id = str(me.get("id") or me.get("user_id") or "")
        print(f"[auth] user_id={user_id}", flush=True)

        cr = await client.post(
            "/v1/conversations", json={"title": args.title or "code-cap-sidecar"}
        )
        cr.raise_for_status()
        conversation_id = str(cr.json()["id"])
        print(f"[conv] conversation_id={conversation_id}", flush=True)

        # Best-effort bind (Desktop-minted root_id). Sidecar still uses abs workspaceRoot.
        br = await client.put(
            f"/v1/conversations/{conversation_id}/workspace/binding",
            json={"root_id": root_id},
        )
        print(f"[bind] status={br.status_code} body={br.text[:200]}", flush=True)

        inference = await _mint_inference(client, args.base_url)
        print(f"[inference] model={inference['model']}", flush=True)

    py = _venv_python()
    env = {**os.environ, "PYTHONUTF8": "1", "AGENTCORE_RELOAD": "false"}
    proc = subprocess.Popen(
        [str(py), "-m", "agentcore.sidecar"],
        cwd=str(SERVER_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
    )

    # Drain stderr so the pipe never blocks.
    async def _stderr() -> None:
        assert proc.stderr is not None
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, proc.stderr.readline)
            if line == "":
                return
            sys.stderr.write(f"[sidecar] {line}")
            sys.stderr.flush()

    rpc = SidecarRpc(proc)
    rpc.start()
    stderr_task = asyncio.create_task(_stderr())

    try:
        await rpc.request(
            "initialize",
            {
                "userId": "local",
                "workspaceRoot": str(workspace),
                "approvalsEnabled": True,
                "dataDir": str(data_dir),
                "permissionPreset": "full_trust",
                "inference": inference,
            },
        )
        print(f"[sidecar] initialized root={workspace}", flush=True)

        turn_task = asyncio.create_task(
            rpc.request(
                "startTurn",
                {
                    "turnId": turn_id,
                    "conversationId": conversation_id,
                    "traceId": trace_id,
                    "userMessage": prompt,
                    "userMessageId": user_message_id,
                    "history": [],
                    "inference": inference,
                    "permissionPreset": "full_trust",
                },
            )
        )

        t0 = time.time()
        while not turn_task.done():
            try:
                note = await asyncio.wait_for(rpc.notify_drain(), timeout=1.0)
            except TimeoutError:
                if time.time() - t0 > args.timeout:
                    raise SystemExit(f"timeout after {args.timeout}s")
                continue
            if note.get("method") != "turn/event":
                continue
            params = note.get("params") or {}
            ev = params.get("event") or {}
            ev_type = str(ev.get("type") or "")
            payload = ev.get("payload") or {}
            events.append({"type": ev_type, "payload": payload, "t": time.time() - t0})
            if ev_type in {
                "tool_use_start",
                "tool_use_end",
                "message_end",
                "error",
                "approval_required",
                "run_plan",
                "question_posted",
                "plan_review_required",
            }:
                extra = ""
                if ev_type.startswith("tool_"):
                    extra = f" {payload.get('tool_name')}"
                elif ev_type == "error":
                    extra = f" {payload.get('code')}: {payload.get('message')}"
                print(f"  +{time.time() - t0:6.1f}s  {ev_type}{extra}", flush=True)
            await _auto_respond(rpc, conversation_id, ev_type, payload)

        result = await turn_task
        print(f"[done] startTurn result keys={list(result.keys()) if isinstance(result, dict) else type(result)}", flush=True)
    finally:
        with contextlib.suppress(Exception):
            await rpc.request("shutdown", {})
        await rpc.close()
        stderr_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stderr_task

    out = OUT_DIR / f"probe_sidecar_{int(time.time())}.json"
    out.write_text(
        json.dumps(
            {
                "conversation_id": conversation_id,
                "trace_id": trace_id,
                "turn_id": turn_id,
                "user_message_id": user_message_id,
                "root_id": root_id,
                "workspace": str(workspace),
                "events": events,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[out] {out}", flush=True)
    print(f"conversation_id={conversation_id}", flush=True)
    print(f"trace_id={trace_id}", flush=True)
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--title", default="code-cap-S2")
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--password", default=DEFAULT_PASS)
    p.add_argument("--timeout", type=int, default=900)
    args = p.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
