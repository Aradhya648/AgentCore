"""真跑探针：同对话再发 P0+P1（平台 DeepSeek）。

场景：
1. 空闲开跑 + mid-flight steer → 期望 turn_steer_accepted
2. mid-flight queue → 期望 turn_queued；再 cancel → 200
3. 缺 delivery → 422
4.（可选）长跑末段再 steer，观察是否 degraded 升队

用法（apps/server）::

    uv run python scripts/probe_delivery_steer_live.py

需本地 API :8000 + 平台凭据；账号默认 dev/devpassword。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE = "http://127.0.0.1:8000"
USER = "dev"
PASSWORD = "devpassword"


@dataclass
class CaseResult:
    name: str
    ok: bool
    detail: str
    events: list[str] = field(default_factory=list)
    conversation_id: str = ""
    trace_hints: list[str] = field(default_factory=list)


async def _login(client: httpx.AsyncClient) -> None:
    r = await client.post(
        f"{BASE}/v1/auth/login",
        json={"username": USER, "password": PASSWORD},
    )
    r.raise_for_status()
    csrf = client.cookies.get("csrf_token") or ""
    if csrf:
        client.headers["X-CSRF-Token"] = csrf


async def _create_conv(client: httpx.AsyncClient, title: str) -> str:
    r = await client.post(
        f"{BASE}/v1/conversations",
        json={"title": title},
    )
    r.raise_for_status()
    data = r.json()
    cid = data.get("id") or data.get("data", {}).get("id")
    if not cid:
        raise RuntimeError(f"create conversation unexpected: {data!r}")
    return str(cid)


async def _iter_sse(resp: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    event_type = ""
    data_lines: list[str] = []
    async for line in resp.aiter_lines():
        if line is None:
            continue
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "":
            if not data_lines:
                event_type = ""
                continue
            raw = "\n".join(data_lines)
            data_lines = []
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                event_type = ""
                continue
            if isinstance(payload, dict):
                et = payload.get("type") or event_type
                if et:
                    payload = {**payload, "type": et}
                yield payload
            event_type = ""


async def _post_messages_sse(
    client: httpx.AsyncClient,
    cid: str,
    *,
    content: str,
    delivery: str | None,
) -> tuple[int, list[dict[str, Any]]]:
    body: dict[str, Any] = {"content": content}
    if delivery is not None:
        body["delivery"] = delivery
    events: list[dict[str, Any]] = []
    async with client.stream(
        "POST",
        f"{BASE}/v1/conversations/{cid}/messages",
        json=body,
        timeout=httpx.Timeout(120.0, connect=10.0),
    ) as resp:
        status = resp.status_code
        if status >= 400:
            # drain error body
            text = ""
            async for chunk in resp.aiter_text():
                text += chunk
            try:
                events.append({"type": "_http_error", "status": status, "body": json.loads(text)})
            except Exception:
                events.append({"type": "_http_error", "status": status, "body": text[:500]})
            return status, events
        async for ev in _iter_sse(resp):
            events.append(ev)
            # short streams (steer ack / queue ack) end quickly; long turn we stop after key events
            t = ev.get("type")
            if t in {
                "turn_steer_accepted",
                "turn_queued",
                "user_interjection",
                "message_end",
                "error",
            }:
                # for long first turn keep going until message_end OR enough progress
                if delivery == "steer" and t == "turn_steer_accepted":
                    break
                if delivery == "queue" and t == "turn_queued":
                    break
                if t == "message_end":
                    break
                if t == "error":
                    break
            # first idle turn: break after we saw tool or substantial content, leave connection
            if delivery == "steer" and t in {"tool_call_start", "content_delta", "run_plan"}:
                # don't break on first delta — need mid-flight window; caller uses parallel
                pass
        return status, events


async def _collect_until(
    client: httpx.AsyncClient,
    cid: str,
    *,
    content: str,
    delivery: str,
    stop_types: set[str],
    max_seconds: float = 90.0,
    also_keep_alive: bool = False,
) -> tuple[int, list[dict[str, Any]]]:
    """POST messages and collect SSE until any stop_types or timeout."""
    body = {"content": content, "delivery": delivery}
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + max_seconds
    async with client.stream(
        "POST",
        f"{BASE}/v1/conversations/{cid}/messages",
        json=body,
        timeout=httpx.Timeout(max_seconds + 30, connect=10.0),
    ) as resp:
        status = resp.status_code
        if status >= 400:
            text = ""
            async for chunk in resp.aiter_text():
                text += chunk
            try:
                events.append({"type": "_http_error", "status": status, "body": json.loads(text)})
            except Exception:
                events.append({"type": "_http_error", "status": status, "body": text[:500]})
            return status, events
        async for ev in _iter_sse(resp):
            events.append(ev)
            t = str(ev.get("type") or "")
            if t in stop_types and not also_keep_alive:
                break
            if time.monotonic() > deadline:
                events.append({"type": "_timeout"})
                break
        return status, events


def _types(events: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for ev in events:
        t = ev.get("type")
        if t:
            out.append(str(t))
    return out


def _find(events: list[dict[str, Any]], typ: str) -> dict[str, Any] | None:
    for ev in events:
        if ev.get("type") == typ:
            return ev
    return None


async def case_missing_delivery(client: httpx.AsyncClient) -> CaseResult:
    cid = await _create_conv(client, "probe-delivery-missing")
    status, events = await _post_messages_sse(
        client, cid, content="ping", delivery=None
    )
    ok = status == 422
    return CaseResult(
        name="missing_delivery_422",
        ok=ok,
        detail=f"status={status}",
        events=_types(events),
        conversation_id=cid,
    )


async def case_steer_midflight(client: httpx.AsyncClient) -> CaseResult:
    """Start a long solo turn, then steer mid-flight."""
    cid = await _create_conv(client, "probe-steer-midflight")
    long_prompt = (
        "不要委派团队。请写一篇约 800 字的短文，主题「中国五个朝代的制度遗产」，"
        "分段写，边想边写，不要调用工具，写完再给三句总结。"
    )

    turn_events: list[dict[str, Any]] = []
    steer_events: list[dict[str, Any]] = []
    status1 = 0
    status2 = 0
    inflight = asyncio.Event()

    async def run_main() -> None:
        nonlocal status1
        body = {"content": long_prompt, "delivery": "steer"}
        async with client.stream(
            "POST",
            f"{BASE}/v1/conversations/{cid}/messages",
            json=body,
            timeout=httpx.Timeout(180.0, connect=10.0),
        ) as resp:
            status1 = resp.status_code
            if status1 >= 400:
                text = ""
                async for chunk in resp.aiter_text():
                    text += chunk
                turn_events.append({"type": "_http_error", "status": status1, "body": text[:300]})
                inflight.set()
                return
            async for ev in _iter_sse(resp):
                turn_events.append(ev)
                t = str(ev.get("type") or "")
                if t in {
                    "message_start",
                    "run_started",
                    "reasoning_delta",
                    "content_delta",
                    "tool_call_start",
                }:
                    inflight.set()
                if t in {"message_end", "error"}:
                    break

    async def run_steer_after_delay() -> None:
        nonlocal status2, steer_events
        try:
            await asyncio.wait_for(inflight.wait(), timeout=90.0)
        except TimeoutError:
            steer_events = [{"type": "_never_started"}]
            return
        await asyncio.sleep(0.5)
        if any(e.get("type") == "message_end" for e in turn_events):
            steer_events = [{"type": "_main_ended_before_steer"}]
            return
        status2, steer_events = await _collect_until(
            client,
            cid,
            content="补充：总结里请额外点明哪个朝代最晚建立。",
            delivery="steer",
            stop_types={
                "turn_steer_accepted",
                "turn_queued",
                "user_interjection",
                "message_end",
                "error",
                "_timeout",
            },
            max_seconds=60.0,
        )

    await asyncio.gather(run_main(), run_steer_after_delay())

    accepted = _find(steer_events, "turn_steer_accepted")
    queued = _find(steer_events, "turn_queued")
    degraded = None
    if queued:
        p = queued.get("payload") or queued
        degraded = p.get("degraded_from")

    if accepted:
        ok = True
        detail = f"turn_steer_accepted steer_id={((accepted.get('payload') or accepted).get('steer_id'))}"
    elif queued and degraded == "steer":
        ok = False
        detail = f"degraded_to_queue degraded_from={degraded}"
    elif _find(steer_events, "_main_ended_before_steer"):
        ok = False
        detail = "main_ended_before_steer (window too short)"
    else:
        ok = False
        detail = f"status2={status2} types={_types(steer_events)[:12]}"

    return CaseResult(
        name="classic_steer_midflight",
        ok=ok,
        detail=detail,
        events=_types(steer_events)[:20],
        conversation_id=cid,
        trace_hints=[f"main_status={status1}", f"main_types={_types(turn_events)[:12]}"],
    )


async def case_queue_and_cancel(client: httpx.AsyncClient) -> CaseResult:
    cid = await _create_conv(client, "probe-queue-cancel")
    long_prompt = (
        "不要委派、不要工具。请从 1 慢慢数到 60，每个数字单独一行；"
        "数完后用两句话总结。"
    )

    turn_events: list[dict[str, Any]] = []
    queue_events: list[dict[str, Any]] = []
    status_q = 0
    cancel_status = 0
    cancel_body: Any = None
    inflight = asyncio.Event()

    async def run_main() -> None:
        body = {"content": long_prompt, "delivery": "steer"}
        async with client.stream(
            "POST",
            f"{BASE}/v1/conversations/{cid}/messages",
            json=body,
            timeout=httpx.Timeout(180.0, connect=10.0),
        ) as resp:
            if resp.status_code >= 400:
                inflight.set()
                return
            async for ev in _iter_sse(resp):
                turn_events.append(ev)
                t = str(ev.get("type") or "")
                if t in {
                    "message_start",
                    "run_started",
                    "reasoning_delta",
                    "content_delta",
                }:
                    inflight.set()
                if t in {"message_end", "error"}:
                    break

    async def run_queue_cancel() -> None:
        nonlocal status_q, queue_events, cancel_status, cancel_body
        try:
            await asyncio.wait_for(inflight.wait(), timeout=90.0)
        except TimeoutError:
            queue_events = [{"type": "_never_started"}]
            return
        await asyncio.sleep(0.5)
        if any(e.get("type") == "message_end" for e in turn_events):
            queue_events = [{"type": "_main_ended_before_queue"}]
            return
        status_q, queue_events = await _collect_until(
            client,
            cid,
            content="这条应排队：稍后请只回复「排队项已到达」。",
            delivery="queue",
            stop_types={"turn_queued", "turn_steer_accepted", "error", "_timeout"},
            max_seconds=45.0,
        )
        queued = _find(queue_events, "turn_queued")
        if not queued:
            return
        p = queued.get("payload") or queued
        qid = p.get("queue_id")
        if not qid:
            return
        r = await client.post(
            f"{BASE}/v1/conversations/{cid}/queued-turns/{qid}/cancel",
            json={},
        )
        cancel_status = r.status_code
        try:
            cancel_body = r.json()
        except Exception:
            cancel_body = r.text[:200]

    await asyncio.gather(run_main(), run_queue_cancel())

    queued = _find(queue_events, "turn_queued")
    ok = bool(queued) and cancel_status == 200
    detail = (
        f"queued={bool(queued)} cancel_status={cancel_status} "
        f"queue_id={((queued or {}).get('payload') or queued or {}).get('queue_id')}"
    )
    return CaseResult(
        name="queue_then_cancel",
        ok=ok,
        detail=detail,
        events=_types(queue_events)[:15],
        conversation_id=cid,
        trace_hints=[f"cancel_body={cancel_body!r}"],
    )


async def case_steer_drains_after_tool(client: httpx.AsyncClient) -> CaseResult:
    """多轮工具：在 tool_call 期间 steer，期望同回合 drain（engine.turn_steer_inject），而非 leftover promote。"""
    cid = await _create_conv(client, "probe-steer-after-tool")
    long_prompt = (
        "必须使用 web_search 工具，禁止委派。"
        "严格按顺序做三次搜索并等待每次结果："
        "①「秦朝建立年份」②「汉朝建立年份」③「唐朝建立年份」。"
        "三次都完成后，再用五句话总结。在第三次搜索完成前不要写总结。"
    )

    turn_events: list[dict[str, Any]] = []
    steer_events: list[dict[str, Any]] = []
    status2 = 0
    tool_seen = asyncio.Event()
    main_done = asyncio.Event()

    async def run_main() -> None:
        body = {"content": long_prompt, "delivery": "steer"}
        async with client.stream(
            "POST",
            f"{BASE}/v1/conversations/{cid}/messages",
            json=body,
            timeout=httpx.Timeout(240.0, connect=10.0),
        ) as resp:
            if resp.status_code >= 400:
                tool_seen.set()
                main_done.set()
                return
            async for ev in _iter_sse(resp):
                turn_events.append(ev)
                t = str(ev.get("type") or "")
                if t in {"tool_use_start", "tool_use_progress", "tool_use_end", "tool_progress"}:
                    tool_seen.set()
                if t in {"message_end", "error"}:
                    break
        main_done.set()

    async def run_steer() -> None:
        nonlocal status2, steer_events
        try:
            await asyncio.wait_for(tool_seen.wait(), timeout=120.0)
        except TimeoutError:
            steer_events = [{"type": "_no_tool"}]
            return
        await asyncio.sleep(0.8)
        if main_done.is_set():
            steer_events = [{"type": "_main_ended_before_steer"}]
            return
        status2, steer_events = await _collect_until(
            client,
            cid,
            content="【同回合注入标记】请在最终总结第一句原样写出：STEER_INJECT_OK",
            delivery="steer",
            stop_types={
                "turn_steer_accepted",
                "turn_queued",
                "error",
                "_timeout",
            },
            max_seconds=60.0,
        )
        await asyncio.wait_for(main_done.wait(), timeout=180.0)

    await asyncio.gather(run_main(), run_steer())

    accepted = _find(steer_events, "turn_steer_accepted")
    if not accepted:
        return CaseResult(
            name="steer_drain_after_tool",
            ok=False,
            detail=f"no accepted; types={_types(steer_events)[:10]}",
            events=_types(steer_events),
            conversation_id=cid,
            trace_hints=[f"main_types={_types(turn_events)[:15]}"],
        )

    steer_id = str((accepted.get("payload") or accepted).get("steer_id") or "")
    # 等日志落盘
    await asyncio.sleep(1.0)
    from pathlib import Path

    log_path = Path(__file__).resolve().parents[3] / "logs" / "dev.jsonl"
    injected = False
    promoted = False
    drained = False
    if log_path.is_file():
        with log_path.open(encoding="utf-8") as f:
            for line in f:
                if cid not in line and steer_id not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                ev = str(o.get("event") or "")
                if ev == "engine.turn_steer_inject" and o.get("conversation_id") == cid:
                    injected = True
                if ev == "turn_steer.drained" and (
                    o.get("conversation_id") == cid or steer_id in line
                ):
                    drained = True
                if (
                    ev == "turn_steer.promoted_to_queue"
                    and o.get("steer_id") == steer_id
                ):
                    promoted = True

    # 成功：同回合注入；若无工具导致无法第二轮则 promoted 可接受但标失败（本 case 目标是 drain）
    ok = bool(accepted) and injected and not promoted
    detail = (
        f"steer_id={steer_id} injected={injected} drained_log={drained} "
        f"promoted={promoted} tools={any(t.startswith('tool_') for t in _types(turn_events))}"
    )
    return CaseResult(
        name="steer_drain_after_tool",
        ok=ok,
        detail=detail,
        events=_types(steer_events)[:12],
        conversation_id=cid,
        trace_hints=[f"main_types={_types(turn_events)[:16]}"],
    )


async def case_queue_runs_after_main(client: httpx.AsyncClient) -> CaseResult:
    """排队不取消：主回合结束后应自动开下一回合，且正文含标记。"""
    cid = await _create_conv(client, "probe-queue-runs")
    long_prompt = (
        "不要工具、不要委派。请写 400 字短文「春天」，分段写完即可。"
    )
    turn_events: list[dict[str, Any]] = []
    queue_events: list[dict[str, Any]] = []
    inflight = asyncio.Event()
    main_done = asyncio.Event()

    async def run_main() -> None:
        body = {"content": long_prompt, "delivery": "steer"}
        async with client.stream(
            "POST",
            f"{BASE}/v1/conversations/{cid}/messages",
            json=body,
            timeout=httpx.Timeout(180.0, connect=10.0),
        ) as resp:
            if resp.status_code >= 400:
                inflight.set()
                main_done.set()
                return
            async for ev in _iter_sse(resp):
                turn_events.append(ev)
                t = str(ev.get("type") or "")
                if t in {"message_start", "run_started", "reasoning_delta", "content_delta"}:
                    inflight.set()
                if t in {"message_end", "error"}:
                    break
        main_done.set()

    async def run_queue() -> None:
        nonlocal queue_events
        try:
            await asyncio.wait_for(inflight.wait(), timeout=90.0)
        except TimeoutError:
            queue_events = [{"type": "_never_started"}]
            return
        await asyncio.sleep(0.4)
        _, queue_events = await _collect_until(
            client,
            cid,
            content="【排队标记】请只回复一行：QUEUE_ITEM_OK",
            delivery="queue",
            stop_types={"turn_queued", "error", "_timeout"},
            max_seconds=45.0,
        )
        # 等主回合结束 + drain 启动的第二回合落库
        await asyncio.wait_for(main_done.wait(), timeout=180.0)
        await asyncio.sleep(8.0)

    await asyncio.gather(run_main(), run_queue())

    queued = _find(queue_events, "turn_queued")
    if not queued:
        return CaseResult(
            name="queue_runs_after_main",
            ok=False,
            detail=f"no turn_queued; types={_types(queue_events)}",
            events=_types(queue_events),
            conversation_id=cid,
        )

    # 读消息列表看是否出现 QUEUE_ITEM_OK
    r = await client.get(f"{BASE}/v1/conversations/{cid}/messages")
    r.raise_for_status()
    data = r.json()
    msgs = data.get("data") or data.get("messages") or []
    joined = "\n".join(str(m.get("content") or "") for m in msgs)
    ok = "QUEUE_ITEM_OK" in joined
    return CaseResult(
        name="queue_runs_after_main",
        ok=ok,
        detail=f"queued=True marker_in_msgs={ok} msg_count={len(msgs)}",
        events=_types(queue_events)[:8],
        conversation_id=cid,
    )


async def case_stop_then_cancel_queue(client: httpx.AsyncClient) -> CaseResult:
    """Stop 不清队：主回合 Stop 后 FIFO 会 drain 启动排队项（常已不可 cancel）。

    断言：排队成功；Stop 后要么仍能 cancel(200)，要么排队正文已作为新回合执行（404=已开跑）。
    """
    cid = await _create_conv(client, "probe-stop-cancel-queue")
    long_prompt = (
        "不要工具。请从 1 数到 100，每个数字一行；数完再总结。"
    )
    turn_events: list[dict[str, Any]] = []
    queue_events: list[dict[str, Any]] = []
    inflight = asyncio.Event()
    cancel_status = 0

    async def run_main() -> None:
        body = {"content": long_prompt, "delivery": "steer"}
        async with client.stream(
            "POST",
            f"{BASE}/v1/conversations/{cid}/messages",
            json=body,
            timeout=httpx.Timeout(180.0, connect=10.0),
        ) as resp:
            if resp.status_code >= 400:
                inflight.set()
                return
            async for ev in _iter_sse(resp):
                turn_events.append(ev)
                t = str(ev.get("type") or "")
                if t in {"message_start", "run_started", "reasoning_delta", "content_delta"}:
                    inflight.set()
                if t in {"message_end", "error"}:
                    break

    async def run_queue_stop_cancel() -> None:
        nonlocal queue_events, cancel_status
        try:
            await asyncio.wait_for(inflight.wait(), timeout=90.0)
        except TimeoutError:
            queue_events = [{"type": "_never_started"}]
            return
        await asyncio.sleep(0.5)
        _, queue_events = await _collect_until(
            client,
            cid,
            content="【Stop后队列】请只回复一行：AFTER_STOP_QUEUE_OK",
            delivery="queue",
            stop_types={"turn_queued", "error", "_timeout"},
            max_seconds=45.0,
        )
        queued = _find(queue_events, "turn_queued")
        if not queued:
            return
        sr = await client.post(f"{BASE}/v1/conversations/{cid}/stop", json={})
        if sr.status_code >= 400:
            queue_events.append({"type": "_stop_failed", "status": sr.status_code})
            return
        await asyncio.sleep(0.3)
        qid = ((queued.get("payload") or queued).get("queue_id"))
        cr = await client.post(
            f"{BASE}/v1/conversations/{cid}/queued-turns/{qid}/cancel",
            json={},
        )
        cancel_status = cr.status_code
        # 给 drain 开跑一点时间
        await asyncio.sleep(6.0)

    await asyncio.gather(run_main(), run_queue_stop_cancel())
    queued = _find(queue_events, "turn_queued")
    r = await client.get(f"{BASE}/v1/conversations/{cid}/messages")
    r.raise_for_status()
    data = r.json()
    msgs = data.get("data") or data.get("messages") or []
    joined = "\n".join(str(m.get("content") or "") for m in msgs)
    ran = "AFTER_STOP_QUEUE_OK" in joined
    # Stop 不清队：200=仍可撤；404+已执行=被 drain 开跑（仍证明未被丢弃）
    ok = bool(queued) and (cancel_status == 200 or (cancel_status == 404 and ran))
    return CaseResult(
        name="stop_then_cancel_queue",
        ok=ok,
        detail=f"queued={bool(queued)} cancel_status={cancel_status} drained_ran={ran}",
        events=_types(queue_events)[:12],
        conversation_id=cid,
    )


async def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument(
        "--suite",
        choices=("smoke", "extended", "all"),
        default="all",
        help="smoke=前三例；extended=多轮注入/排队执行/Stop+取消；all=全部",
    )
    args = p.parse_args()

    results: list[CaseResult] = []
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        await _login(client)
        if args.suite in {"smoke", "all"}:
            results.append(await case_missing_delivery(client))
            results.append(await case_steer_midflight(client))
            results.append(await case_queue_and_cancel(client))
        if args.suite in {"extended", "all"}:
            results.append(await case_steer_drains_after_tool(client))
            results.append(await case_queue_runs_after_main(client))
            results.append(await case_stop_then_cancel_queue(client))

    print("=== probe_delivery_steer_live (platform DeepSeek) ===")
    failed = 0
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        if not r.ok:
            failed += 1
        print(f"[{mark}] {r.name}: {r.detail}")
        print(f"       conv={r.conversation_id}")
        if r.events:
            print(f"       events={r.events}")
        for h in r.trace_hints:
            print(f"       {h}")
    print(f"=== done: {len(results) - failed}/{len(results)} passed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
