"""HTTP walkthrough of demo-tape prepare / auto-start (dev-only).

Prereq: backend running with ``DEMO_TAPE_REPLAY_ENABLED=true``.

From apps/server::

    # Primary: prepare → user message → stream + resume
    uv run python scripts/demo_tape_http_walk.py --tape lv-molihua-trademark

    # Auto-start (smoke / legacy one-click)
    uv run python scripts/demo_tape_http_walk.py --tape lv-molihua-trademark --autostart

    # Legacy: already-bound conversation + send trigger message
    uv run python scripts/demo_tape_http_walk.py --conversation <id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any

import httpx

DEFAULT_BASE_URL = os.environ.get("PROBE_BASE_URL", "http://localhost:8000")
DEFAULT_USERNAME = os.environ.get("DEV_USERNAME", "dev")
DEFAULT_PASSWORD = os.environ.get("DEV_PASSWORD", "devpassword")
DEFAULT_TAPE = os.environ.get("DEMO_TAPE_ID", "lv-molihua-trademark")
# Distinct from tape meta so we can assert the displayed user message == send text.
TRIGGER_MESSAGE = "（准备模式自测）开场触发磁带回放"


async def _login(client: httpx.AsyncClient, base: str, user: str, pw: str) -> str:
    r = await client.post(f"{base}/v1/auth/token", json={"username": user, "password": pw})
    r.raise_for_status()
    return r.json()["access_token"]


def _parse_sse_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def _read_until(
    resp: httpx.Response,
    *,
    stop_types: set[str],
    start: float,
    max_seconds: float,
    collected: list[tuple[int, str, dict]],
) -> str | None:
    """Read SSE until one of stop_types; return the stopping event type."""
    async for line in resp.aiter_lines():
        if (time.monotonic() - start) > max_seconds:
            raise SystemExit(f"timeout after {max_seconds}s")
        ev = _parse_sse_line(line)
        if not ev:
            continue
        et = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        t_ms = int((time.monotonic() - start) * 1000)
        collected.append((t_ms, et, payload if isinstance(payload, dict) else {}))
        print(f"  {t_ms:>7}ms  {et}")
        if et in stop_types:
            return et
    return None


def _is_paused(collected: list[tuple[int, str, dict]]) -> bool:
    return any(
        et == "message_end" and str(p.get("finish_reason") or "").lower() == "paused"
        for _t, et, p in collected
    )


def _assert_user_message_content(
    messages: list[dict[str, Any]], expected: str
) -> None:
    users = [m for m in messages if str(m.get("role") or "") == "user"]
    if not users:
        raise SystemExit(f"no user messages in conversation: {messages[:3]!r}")
    content = str(users[-1].get("content") or "")
    if content != expected:
        raise SystemExit(
            f"user message mismatch: got={content!r} expected={expected!r}"
        )
    print(f"user message ok: {content!r}")


async def walk(args: argparse.Namespace) -> None:
    base = args.base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=None) as client:
        token = await _login(client, base, args.user, args.password)
        headers = {"Authorization": f"Bearer {token}"}
        collected: list[tuple[int, str, dict]] = []
        start = time.monotonic()
        checkpoint_id: str | None = None
        trigger_text: str | None = None

        if args.tape:
            cat = await client.get(f"{base}/v1/demo-tape", headers=headers)
            if cat.status_code == 404:
                raise SystemExit(
                    "GET /v1/demo-tape → 404 — set DEMO_TAPE_REPLAY_ENABLED=true and restart"
                )
            cat.raise_for_status()
            tapes = (cat.json().get("tapes") or [])
            ids = [t.get("id") for t in tapes]
            if args.tape not in ids:
                raise SystemExit(f"tape {args.tape!r} not in catalog: {ids}")

            launch_body: dict[str, Any] = {"tape_id": args.tape}
            if args.speed is not None:
                launch_body["speed"] = args.speed
            if args.max_gap_ms is not None:
                launch_body["max_gap_ms"] = args.max_gap_ms

            if args.autostart:
                print(f"POST /v1/demo-tape/start tape_id={args.tape}")
                started = await client.post(
                    f"{base}/v1/demo-tape/start", headers=headers, json=launch_body
                )
                if started.status_code != 200:
                    raise SystemExit(
                        f"start failed {started.status_code}: {started.text}"
                    )
                start_payload = started.json()
                conv = str(start_payload["conversation_id"])
                trigger_text = str(start_payload.get("user_prompt") or "")
                print(
                    f"  conversation_id={conv} user_prompt={trigger_text!r}"
                )

                print(f"GET stream (attach) → {conv}")
                async with client.stream(
                    "GET",
                    f"{base}/v1/conversations/{conv}/stream",
                    headers={
                        **headers,
                        "Last-Event-ID": "0",
                        "Accept": "text/event-stream",
                    },
                ) as resp:
                    if resp.status_code == 204:
                        print("  attach 204 (no live run) — checking recovery")
                        stopped = None
                    elif resp.status_code != 200:
                        raise SystemExit(
                            f"attach failed {resp.status_code}: {await resp.aread()}"
                        )
                    else:
                        stopped = await _read_until(
                            resp,
                            stop_types={"message_end", "error"},
                            start=start,
                            max_seconds=args.max_seconds,
                            collected=collected,
                        )
            else:
                print(f"POST /v1/demo-tape/prepare tape_id={args.tape}")
                prepared = await client.post(
                    f"{base}/v1/demo-tape/prepare",
                    headers=headers,
                    json=launch_body,
                )
                if prepared.status_code != 200:
                    raise SystemExit(
                        f"prepare failed {prepared.status_code}: {prepared.text}"
                    )
                prep_payload = prepared.json()
                conv = str(prep_payload["conversation_id"])
                suggested = str(prep_payload.get("user_prompt") or "")
                print(
                    f"  conversation_id={conv} suggested_prompt={suggested!r}"
                )

                trigger_text = args.message
                print(f"POST messages → {conv} content={trigger_text!r}")
                async with client.stream(
                    "POST",
                    f"{base}/v1/conversations/{conv}/messages",
                    headers=headers,
                    json={"content": trigger_text},
                ) as resp:
                    if resp.status_code != 200:
                        raise SystemExit(
                            f"send failed {resp.status_code}: {await resp.aread()}"
                        )
                    stopped = await _read_until(
                        resp,
                        stop_types={"message_end", "error"},
                        start=start,
                        max_seconds=args.max_seconds,
                        collected=collected,
                    )
        else:
            conv = args.conversation
            if not conv:
                raise SystemExit("provide --tape <id> or --conversation <id>")
            trigger_text = args.message
            print(f"POST messages → {conv}")
            async with client.stream(
                "POST",
                f"{base}/v1/conversations/{conv}/messages",
                headers=headers,
                json={"content": trigger_text},
            ) as resp:
                if resp.status_code != 200:
                    raise SystemExit(
                        f"send failed {resp.status_code}: {await resp.aread()}"
                    )
                stopped = await _read_until(
                    resp,
                    stop_types={"message_end", "error"},
                    start=start,
                    max_seconds=args.max_seconds,
                    collected=collected,
                )

        for _t, et, payload in collected:
            if et == "team_preview_required":
                checkpoint_id = str(payload.get("checkpoint_id") or "")
        if stopped == "error":
            raise SystemExit("stream ended with error before pause/complete")

        # Opening segment should include search / case-brief style content before pause.
        early_types = {et for _t, et, _p in collected}
        # Still assert we got some assistant activity before pause/complete.
        if (
            "team_preview_required" not in early_types
            and collected
            and not any(
                et in {"text_delta", "tool_call_started", "thinking_delta", "run_started"}
                for et in early_types
            )
        ):
            print(
                f"warn: unusual early event set before pause: {sorted(early_types)[:20]}"
            )

        paused = _is_paused(collected)
        r = await client.get(f"{base}/v1/conversations/{conv}/recovery", headers=headers)
        r.raise_for_status()
        recovery = r.json()
        items = recovery.get("paused") or []

        if not paused and not items:
            if collected:
                print("OK: tape completed without pause (no team_preview on tape?)")
                _assert_gaps(collected, args.max_gap_ms)
                return
            raise SystemExit(f"no stream events and no paused recovery: {recovery}")

        if not items:
            raise SystemExit(f"paused stream but no recovery.paused: {recovery}")
        message_id = str(items[0].get("message_id") or "")
        if not checkpoint_id:
            checkpoint_id = str(items[0].get("checkpoint_id") or "")
        if not message_id:
            raise SystemExit(f"cannot parse paused payload: {items[0]}")
        if not checkpoint_id:
            raise SystemExit("paused but no checkpoint_id on stream or recovery")

        print(f"RESUME message_id={message_id} checkpoint={checkpoint_id}")
        start2 = time.monotonic()
        async with client.stream(
            "POST",
            f"{base}/v1/conversations/{conv}/messages/{message_id}/resume",
            headers=headers,
            json={"decision": "continue", "note": ""},
        ) as resp:
            if resp.status_code != 200:
                raise SystemExit(f"resume failed {resp.status_code}: {await resp.aread()}")
            await _read_until(
                resp,
                stop_types={"message_end", "error"},
                start=start2,
                max_seconds=args.max_seconds,
                collected=collected,
            )

        kinds = [et for _t, et, _p in collected]
        assert "team_preview_required" in kinds
        assert "team_preview_resolved" in kinds
        assert kinds.count("team_preview_resolved") >= 1
        _assert_gaps(collected, args.max_gap_ms)

        if trigger_text and not args.autostart:
            msgs = await client.get(
                f"{base}/v1/conversations/{conv}/messages", headers=headers
            )
            if msgs.status_code == 200:
                body = msgs.json()
                items_list = body.get("data") if isinstance(body, dict) else body
                if isinstance(items_list, list):
                    _assert_user_message_content(items_list, trigger_text)
                else:
                    raise SystemExit(f"unexpected messages body: {body!r}")
            else:
                raise SystemExit(
                    f"GET messages failed {msgs.status_code}: {msgs.text}"
                )

        mode = "autostart" if args.autostart else "prepare"
        print(f"OK: {mode} → pause → resume → complete; gap cap respected")


def _assert_gaps(collected: list[tuple[int, str, dict]], max_gap_ms: int) -> None:
    """Inter-arrival gaps on the client should not greatly exceed max_gap_ms (+slack)."""
    if len(collected) < 2:
        return
    slack = 500  # scheduling / HTTP jitter
    worst = 0
    for (t0, _, _), (t1, _, _) in zip(collected, collected[1:], strict=False):
        gap = t1 - t0
        worst = max(worst, gap)
        if gap > max_gap_ms + slack:
            raise SystemExit(
                f"gap {gap}ms exceeds max_gap_ms={max_gap_ms} (+{slack} slack) "
                f"— check DEMO_TAPE_MAX_GAP_MS / binding"
            )
    print(f"gap check ok (worst_client_gap={worst}ms, cap={max_gap_ms}+{slack})")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--tape",
        default=None,
        help=f"Tape id (filename stem). Default when no --conversation: {DEFAULT_TAPE}",
    )
    p.add_argument(
        "--conversation",
        default=None,
        help="Legacy: already-bound conversation id (sends a trigger message)",
    )
    p.add_argument(
        "--autostart",
        action="store_true",
        help="Use POST /start (auto-start) instead of prepare + send message",
    )
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--user", default=DEFAULT_USERNAME)
    p.add_argument("--password", default=DEFAULT_PASSWORD)
    p.add_argument("--message", default=TRIGGER_MESSAGE)
    p.add_argument("--speed", type=float, default=None)
    p.add_argument("--max-seconds", type=float, default=600)
    p.add_argument(
        "--max-gap-ms",
        type=int,
        default=int(os.environ.get("DEMO_TAPE_MAX_GAP_MS", "2500")),
        help="Client-side gap assertion (should match binding max_gap_ms)",
    )
    args = p.parse_args()
    if not args.conversation and not args.tape:
        args.tape = DEFAULT_TAPE
    asyncio.run(walk(args))


if __name__ == "__main__":
    main()
