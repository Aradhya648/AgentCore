"""每月免费额度端到端验收探针（成本配额与计费.md §〇·五）。

覆盖：无 key 免费档真回合 + 真算价入账、月帽耗尽 429 FREE_TIER_EXHAUSTED、
BYOK 含后台零变化（cost=0、不查配额）、sidecar proxy 入账与耗尽 429 非 402。

从 ``apps/server`` 跑::

    uv run python scripts/probe_free_tier.py

产出 JSON 报告到 stdout，并写 ``logs/probes/free_tier_<ts>.json``。
不改产品代码 / .env；会注册带时间戳的测试用户、调 set_quota 制造耗尽并清回。
全程真实 LLM 回合预算 ≤6（429 拒在 gate、不计入）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from agentcore.db import async_session_factory

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "logs" / "probes"
LOG_PATH = REPO_ROOT / "logs" / "dev.jsonl"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

DEFAULT_BASE = os.environ.get("PROBE_BASE_URL", "http://localhost:8000")
MSG_SIMPLE = "用一句话解释什么是复利"
MSG_SIMPLE_2 = "用一句话解释什么是利息"
MSG_BYOK = "用一句话解释什么是本金"
MSG_BYOK_2 = "用一句话解释什么是利率"


@dataclass
class CheckResult:
    item: int
    name: str
    status: str  # PASS | FAIL | SKIP
    evidence: dict[str, Any] = field(default_factory=dict)
    note: str = ""


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _ts_user(prefix: str) -> str:
    return f"{prefix}_{time.strftime('%Y%m%d%H%M%S')}"


async def _register(client: httpx.AsyncClient, base: str, user: str, pw: str) -> dict[str, Any]:
    r = await client.post(
        f"{base}/v1/auth/register",
        json={"username": user, "password": pw, "display_name": f"FT {user}"},
    )
    r.raise_for_status()
    return r.json()


async def _login(client: httpx.AsyncClient, base: str, user: str, pw: str) -> str:
    r = await client.post(f"{base}/v1/auth/token", json={"username": user, "password": pw})
    r.raise_for_status()
    return r.json()["access_token"]


async def _llm_key_status(client: httpx.AsyncClient, base: str, token: str) -> dict[str, Any]:
    r = await client.get(
        f"{base}/v1/users/me/llm-providers", headers={"Authorization": f"Bearer {token}"}
    )
    r.raise_for_status()
    data = r.json()
    # 多服务商列表：'configured' 派生自是否有 provider（部署级字段仍在列表响应里）。
    data["configured"] = bool(data.get("providers"))
    return data


async def _create_conv(client: httpx.AsyncClient, base: str, token: str, title: str = "") -> str:
    # Empty title so background title mint runs (non-empty title skips mint).
    r = await client.post(
        f"{base}/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": title},
    )
    r.raise_for_status()
    return r.json()["id"]


async def _send_message(
    client: httpx.AsyncClient,
    base: str,
    token: str,
    conv_id: str,
    content: str,
    *,
    max_seconds: float = 180.0,
) -> dict[str, Any]:
    """POST message; return status + SSE summary (or JSON error body)."""
    url = f"{base}/v1/conversations/{conv_id}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    events: list[dict[str, Any]] = []
    start = time.monotonic()
    async with client.stream("POST", url, headers=headers, json={"content": content}) as resp:
        status = resp.status_code
        ctype = resp.headers.get("content-type", "")
        if status != 200 or "text/event-stream" not in ctype:
            body = (await resp.aread()).decode("utf-8", "replace")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"raw": body}
            return {
                "http_status": status,
                "ok": False,
                "error_body": parsed,
                "events": [],
                "message_id": None,
                "finish_reason": None,
                "had_error_event": False,
            }
        async for line in resp.aiter_lines():
            if (time.monotonic() - start) > max_seconds:
                break
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            events.append(ev)
            if ev.get("type") in {"message_end", "error"}:
                break

    message_id = None
    finish_reason = None
    had_error = False
    error_payload: dict[str, Any] | None = None
    for ev in events:
        t = ev.get("type")
        p = ev.get("payload") or {}
        if t == "message_start":
            message_id = p.get("message_id") or p.get("id") or message_id
        if t == "message_end":
            message_id = p.get("message_id") or message_id
            finish_reason = p.get("finish_reason")
        if t == "error":
            had_error = True
            error_payload = p
    return {
        "http_status": status,
        "ok": status == 200 and not had_error and finish_reason is not None,
        "events": [{"type": e.get("type"), "payload_keys": list((e.get("payload") or {}).keys())} for e in events],
        "event_types": [e.get("type") for e in events],
        "message_id": message_id,
        "finish_reason": finish_reason,
        "had_error_event": had_error,
        "error_payload": error_payload,
        "elapsed_ms": int((time.monotonic() - start) * 1000),
    }


async def _get_json(client: httpx.AsyncClient, base: str, token: str, path: str) -> Any:
    r = await client.get(f"{base}{path}", headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


async def _put_llm_key(
    client: httpx.AsyncClient,
    base: str,
    token: str,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    r = await client.post(
        f"{base}/v1/users/me/llm-providers",
        headers={"Authorization": f"Bearer {token}"},
        json={"label": "DeepSeek", "api_key": api_key, "base_url": base_url, "default_model": model},
    )
    r.raise_for_status()
    return r.json()


async def _set_quota(username: str, monthly_usd: float | None) -> str:
    """Call set_quota semantics via UserRepository (same as scripts/set_quota.py)."""
    from agentcore.db.repositories import UserRepository

    async with async_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_username(username)
        if user is None:
            raise RuntimeError(f"user {username!r} not found")
        await users.set_quota(user.user_id, monthly_cost_usd=monthly_usd)
        user = await users.get_by_id(user.user_id)
        return (
            f"user={username} monthly={user.quota_monthly_cost_usd!r} "
            f"unlimited={user.is_unlimited}"
        )


async def _db_cost_rows(user_id: str, message_id: str | None) -> dict[str, Any]:
    async with async_session_factory() as session:
        calls = (
            await session.execute(
                text(
                    """
                    SELECT call_id, role, model, cost_total_nano, message_id, run_id
                    FROM cost_calls
                    WHERE user_id = :uid
                    ORDER BY created_at
                    """
                ),
                {"uid": user_id},
            )
        ).mappings().all()
        events = (
            await session.execute(
                text(
                    """
                    SELECT run_id, role, model, cost_total_nano, message_id
                    FROM cost_events
                    WHERE user_id = :uid
                    ORDER BY created_at
                    """
                ),
                {"uid": user_id},
            )
        ).mappings().all()
        def _row(r: Any) -> dict[str, Any]:
            d = dict(r)
            # asyncpg may return UUID objects — normalize for JSON + str compare.
            for k in ("message_id", "user_id", "call_id"):
                if k in d and d[k] is not None:
                    d[k] = str(d[k])
            if "cost_total_nano" in d and d["cost_total_nano"] is not None:
                d["cost_total_nano"] = int(d["cost_total_nano"])
            return d

        mid = str(message_id) if message_id else None
        all_calls = [_row(r) for r in calls]
        all_events = [_row(r) for r in events]
        msg_calls = [r for r in all_calls if mid and r.get("message_id") == mid]
        msg_events = [r for r in all_events if mid and r.get("message_id") == mid]
        return {
            "calls_total": len(all_calls),
            "events_total": len(all_events),
            "calls_for_message": msg_calls,
            "events_for_message": msg_events,
            "calls_sum_nano": sum(int(r["cost_total_nano"] or 0) for r in all_calls),
            "events_sum_nano": sum(int(r["cost_total_nano"] or 0) for r in all_events),
        }


def _tail_llm_calls(
    *,
    user_id: str | None = None,
    scenario: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Parse ``event=llm.call`` JSON lines from logs/dev.jsonl."""
    if not LOG_PATH.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]:
        if '"event": "llm.call"' not in line:
            continue
        if user_id and user_id not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") != "llm.call":
            continue
        if scenario and obj.get("scenario") != scenario:
            continue
        rows.append(
            {
                "scenario": obj.get("scenario"),
                "cost_nano": obj.get("cost_nano"),
                "model": obj.get("model"),
                "credential_source": obj.get("credential_source"),
                "user_id": obj.get("user_id"),
                "input_tokens": obj.get("input_tokens"),
                "output_tokens": obj.get("output_tokens"),
                "timestamp": obj.get("timestamp"),
            }
        )
    return rows[-limit:]


def _wait_title_call(
    user_id: str, baseline_n: int, deadline_s: float = 60.0, poll: float = 1.5
) -> dict[str, Any] | None:
    """Poll log for a new scenario=title llm.call for ``user_id``."""
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        time.sleep(poll)
        cur = _tail_llm_calls(user_id=user_id, scenario="title", limit=50)
        if len(cur) > baseline_n:
            return cur[-1]
    return None


async def _proxy_chat(
    client: httpx.AsyncClient,
    base: str,
    user_token: str,
    prompt: str,
    *,
    conversation_id: str,
) -> dict[str, Any]:
    mint = await client.post(
        f"{base}/v1/inference/token",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    if mint.status_code != 200:
        return {
            "mint_status": mint.status_code,
            "mint_body": mint.json() if mint.headers.get("content-type", "").startswith("application/json") else mint.text,
            "chat_status": None,
            "chat_body": None,
        }
    mint_j = mint.json()
    inf = mint_j["token"]
    model = mint_j.get("model") or "deepseek-v4-flash"
    body = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32,
    }
    chat = await client.post(
        f"{base}/v1/inference/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {inf}",
            "X-AgentCore-Conversation": conversation_id,
        },
        json=body,
    )
    try:
        chat_body = chat.json()
    except Exception:
        chat_body = {"raw": chat.text[:500]}
    return {
        "mint_status": 200,
        "model": model,
        "chat_status": chat.status_code,
        "chat_body": chat_body,
    }


def _err_code(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    err = body.get("error") or body
    if isinstance(err, dict):
        return err.get("code")
    return None


def _err_msg(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    err = body.get("error") or body
    if isinstance(err, dict):
        return err.get("message")
    return None


async def main() -> int:
    base = DEFAULT_BASE.rstrip("/")
    env = _load_dotenv(ENV_PATH)
    platform_key = env.get("PLATFORM_API_KEY", "")
    platform_url = env.get("PLATFORM_BASE_URL", "https://api.deepseek.com")
    platform_model = env.get("PLATFORM_MODEL", "deepseek-v4-flash")
    if not platform_key:
        print("FAIL: PLATFORM_API_KEY missing in apps/server/.env", file=sys.stderr)
        return 2

    pw = "TestPass1!"
    free_user = _ts_user("ft_free")
    byok_user = _ts_user("ft_byok")
    results: list[CheckResult] = []
    meta: dict[str, Any] = {
        "base": base,
        "free_user": free_user,
        "byok_user": byok_user,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    llm_turns_used = 0

    timeout = httpx.Timeout(300.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        # ── gate: free_tier_active ──────────────────────────────────────
        free_reg = await _register(client, base, free_user, pw)
        free_uid = free_reg["id"]
        free_tok = await _login(client, base, free_user, pw)
        status0 = await _llm_key_status(client, base, free_tok)
        meta["free_tier_active_pre"] = status0.get("free_tier_active")
        meta["platform_available"] = status0.get("platform_available")
        if not status0.get("free_tier_active"):
            results.append(
                CheckResult(
                    0,
                    "free_tier_active precondition",
                    "FAIL",
                    evidence={"llm_key_status": status0},
                    note="free_tier_active=false — 需重启后端以重读 .env",
                )
            )
            _emit(results, meta, llm_turns_used)
            return 1

        # ── §八.1 无 key 发消息跑完回合 ─────────────────────────────────
        conv1 = await _create_conv(client, base, free_tok, "")
        turn1 = await _send_message(client, base, free_tok, conv1, MSG_SIMPLE)
        llm_turns_used += 1 if turn1.get("ok") else 0
        ok1 = bool(turn1.get("ok") and turn1.get("finish_reason") and not turn1.get("had_error_event"))
        results.append(
            CheckResult(
                1,
                "无 key 新用户直接发消息 → 真实回合完成",
                "PASS" if ok1 else "FAIL",
                evidence={
                    "http_status": turn1.get("http_status"),
                    "finish_reason": turn1.get("finish_reason"),
                    "message_id": turn1.get("message_id"),
                    "had_error_event": turn1.get("had_error_event"),
                    "error_payload": turn1.get("error_payload"),
                    "elapsed_ms": turn1.get("elapsed_ms"),
                    "event_types_sample": (turn1.get("event_types") or [])[:20],
                    "free_tier_active": True,
                },
            )
        )
        if not ok1:
            _emit(results, meta, llm_turns_used)
            return 1

        mid1 = turn1["message_id"]
        # brief settle for ledger drain
        await asyncio.sleep(2.0)

        # ── §八.2 入账 ──────────────────────────────────────────────────
        msg_cost = await _get_json(client, base, free_tok, f"/v1/messages/{mid1}/cost")
        usage_sum = await _get_json(client, base, free_tok, "/v1/usage/summary")
        db_rows = await _db_cost_rows(free_uid, mid1)
        cost_total = int((msg_cost.get("cost") or {}).get("total") or 0)
        # usage summary month cost
        month_cost = int(((usage_sum.get("month") or {}).get("cost") or {}).get("total") or 0)
        if month_cost == 0:
            # alternate shapes
            month_cost = int(usage_sum.get("month_cost_total") or usage_sum.get("cost_total") or 0)
            for k in ("month", "today"):
                block = usage_sum.get(k)
                if isinstance(block, dict) and "cost_total" in block:
                    month_cost = max(month_cost, int(block["cost_total"] or 0))
                if isinstance(block, dict) and isinstance(block.get("cost"), dict):
                    month_cost = max(month_cost, int(block["cost"].get("total") or 0))

        ok2 = (
            cost_total > 0
            and len(db_rows["calls_for_message"]) > 0
            and len(db_rows["events_for_message"]) > 0
            and any(int(c["cost_total_nano"] or 0) > 0 for c in db_rows["calls_for_message"])
            and any(int(e["cost_total_nano"] or 0) > 0 for e in db_rows["events_for_message"])
        )
        results.append(
            CheckResult(
                2,
                "回合入账 cost_calls/cost_events 且 cost_total_nano>0",
                "PASS" if ok2 else "FAIL",
                evidence={
                    "message_id": mid1,
                    "api_message_cost_total": cost_total,
                    "api_message_cost": msg_cost.get("cost"),
                    "api_message_usage": msg_cost.get("usage"),
                    "usage_summary_month_cost_total": month_cost,
                    "usage_summary_keys": list(usage_sum.keys()),
                    "db_calls_for_message": db_rows["calls_for_message"],
                    "db_events_for_message": db_rows["events_for_message"],
                    "db_calls_sum_nano": db_rows["calls_sum_nano"],
                },
            )
        )
        if not ok2:
            _emit(results, meta, llm_turns_used)
            return 1

        spent_nano = max(cost_total, db_rows["calls_sum_nano"], 1)
        # ── §八.3 耗尽 → 429 FREE_TIER_EXHAUSTED ────────────────────────
        q_note = await _set_quota(free_user, 0.000001)
        turn_ex = await _send_message(client, base, free_tok, conv1, MSG_SIMPLE_2)
        # may be non-SSE 429
        http_ex = turn_ex.get("http_status")
        body_ex = turn_ex.get("error_body") or turn_ex.get("error_payload") or {}
        code_ex = _err_code(body_ex) or (turn_ex.get("error_payload") or {}).get("code")
        msg_ex = _err_msg(body_ex) or (turn_ex.get("error_payload") or {}).get("message") or ""
        ok3 = (
            http_ex == 429
            and code_ex == "FREE_TIER_EXHAUSTED"
            and ("免费额度" in str(msg_ex))
        )
        results.append(
            CheckResult(
                3,
                "触及月帽 → 429 FREE_TIER_EXHAUSTED + 转化文案",
                "PASS" if ok3 else "FAIL",
                evidence={
                    "quota_set": q_note,
                    "spent_nano_ref": spent_nano,
                    "http_status": http_ex,
                    "error_code": code_ex,
                    "error_message": msg_ex,
                    "error_body": body_ex,
                    "sse_error": turn_ex.get("error_payload"),
                    "note_utc_reset": "UTC 月初重置由单测覆盖，本项不验",
                },
            )
        )
        await _set_quota(free_user, None)  # inherit
        if not ok3:
            _emit(results, meta, llm_turns_used)
            return 1

        # ── §八.4 BYOK 零变化 ───────────────────────────────────────────
        byok_reg = await _register(client, base, byok_user, pw)
        byok_uid = byok_reg["id"]
        byok_tok = await _login(client, base, byok_user, pw)
        await _put_llm_key(client, base, byok_tok, platform_key, platform_url, platform_model)
        st_byok = await _llm_key_status(client, base, byok_tok)
        conv_b = await _create_conv(client, base, byok_tok, "")
        # Baseline MUST be user-scoped: _wait_title_call polls the user-filtered count,
        # so an all-users baseline can never be exceeded (fallback then grabs another
        # user's title row → false FAIL when that row is platform-billed).
        title_baseline = len(_tail_llm_calls(user_id=byok_uid, scenario="title"))
        turn_t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        turn_b = await _send_message(client, base, byok_tok, conv_b, MSG_BYOK)
        llm_turns_used += 1 if turn_b.get("ok") else 0
        if not turn_b.get("ok"):
            results.append(
                CheckResult(
                    4,
                    "BYOK 用户主回合 + 后台 cost=0、不查配额",
                    "FAIL",
                    evidence={"turn": turn_b, "llm_key_status": st_byok},
                    note="BYOK 回合未成功完成",
                )
            )
            _emit(results, meta, llm_turns_used)
            return 1

        mid_b = turn_b["message_id"]
        await asyncio.sleep(2.0)
        cost_b = await _get_json(client, base, byok_tok, f"/v1/messages/{mid_b}/cost")
        cost_b_total = int((cost_b.get("cost") or {}).get("total") or 0)
        usage_b = cost_b.get("usage") or {}
        tokens_ok = int(usage_b.get("input") or 0) + int(usage_b.get("output") or 0) > 0

        # Title mint may omit user_id in log context — match by scenario + freshness.
        title_row = await asyncio.to_thread(
            _wait_title_call, byok_uid, title_baseline, 60.0, 1.5
        )
        if title_row is None:
            # Fallback: any new title llm.call after turn start (user_id often unbound).
            fresh = [
                r
                for r in _tail_llm_calls(scenario="title", limit=20)
                if (r.get("timestamp") or "") >= turn_t0
            ]
            title_row = fresh[-1] if fresh else None
        # NB: cost_nano=0 is the EXPECTED value here — `x or -1` would coerce it to -1,
        # so missing-vs-zero must be told apart explicitly.
        _title_cost = title_row.get("cost_nano") if title_row is not None else None
        title_cost0 = _title_cost is not None and int(_title_cost) == 0
        # Corroborate with other background purposes that DO bind user_id.
        bg_user = [
            r
            for r in _tail_llm_calls(user_id=byok_uid, limit=30)
            if r.get("scenario") in {"followups", "memory", "title"}
            and r.get("cost_nano") is not None
            and int(r.get("cost_nano")) == 0
        ]

        # quota low should NOT block BYOK。上一回合若仍在飞：POST 恒 200+SSE，
        # 首帧 turn_queued 后同连接续流（202 JSON 已退役；_send_message 读到 message_end）。
        await _set_quota(byok_user, 0.000001)
        turn_b2 = await _send_message(client, base, byok_tok, conv_b, MSG_BYOK_2)
        if turn_b2.get("ok"):
            llm_turns_used += 1
        await _set_quota(byok_user, None)

        ok4 = (
            cost_b_total == 0
            and tokens_ok
            and title_cost0
            and turn_b2.get("http_status") == 200
            and turn_b2.get("ok")
            and st_byok.get("configured") is True
            and st_byok.get("free_tier_active") is False
        )
        results.append(
            CheckResult(
                4,
                "BYOK 用户主回合+后台 cost=0、有 key 不查配额",
                "PASS" if ok4 else "FAIL",
                evidence={
                    "llm_key_status": {
                        "configured": st_byok.get("configured"),
                        "free_tier_active": st_byok.get("free_tier_active"),
                        "billing_mode": st_byok.get("billing_mode"),
                    },
                    "message_id": mid_b,
                    "cost_total": cost_b_total,
                    "usage": usage_b,
                    "title_llm_call": title_row,
                    "background_user_bound_cost0": bg_user[-5:],
                    "quota_low_second_turn": {
                        "http_status": turn_b2.get("http_status"),
                        "ok": turn_b2.get("ok"),
                        "finish_reason": turn_b2.get("finish_reason"),
                        "error": turn_b2.get("error_body") or turn_b2.get("error_payload"),
                    },
                    "byok_user_id": byok_uid,
                },
            )
        )
        if not ok4:
            _emit(results, meta, llm_turns_used)
            return 1

        # ── §八.5 sidecar proxy ─────────────────────────────────────────
        # free user override already cleared
        usage_before = await _get_json(client, base, free_tok, "/v1/usage/summary")
        before_nano = _usage_month_nano(usage_before)
        proxy1 = await _proxy_chat(
            client, base, free_tok, "用三字回答：你好", conversation_id=conv1
        )
        if proxy1.get("chat_status") == 200:
            llm_turns_used += 1
        await asyncio.sleep(3.5)
        usage_after = await _get_json(client, base, free_tok, "/v1/usage/summary")
        after_nano = _usage_month_nano(usage_after)
        grew = after_nano > before_nano

        await _set_quota(free_user, 0.000001)
        proxy2 = await _proxy_chat(client, base, free_tok, "ping", conversation_id=conv1)
        await _set_quota(free_user, None)

        p2_status = proxy2.get("chat_status")
        p2_body = proxy2.get("chat_body") or {}
        p2_code = _err_code(p2_body)
        # mint itself might 429
        if p2_status is None and proxy2.get("mint_status") == 429:
            p2_status = 429
            p2_body = proxy2.get("mint_body") or {}
            p2_code = _err_code(p2_body)

        ok5 = (
            proxy1.get("chat_status") == 200
            and grew
            and p2_status == 429
            and p2_status != 402
            and p2_code == "FREE_TIER_EXHAUSTED"
        )
        results.append(
            CheckResult(
                5,
                "sidecar proxy：成功入账 + 耗尽 429(非402) FREE_TIER_EXHAUSTED",
                "PASS" if ok5 else "FAIL",
                evidence={
                    "proxy_ok": {
                        "mint_status": proxy1.get("mint_status"),
                        "chat_status": proxy1.get("chat_status"),
                        "model": proxy1.get("model"),
                        "usage_before_nano": before_nano,
                        "usage_after_nano": after_nano,
                        "grew": grew,
                        "chat_preview": _proxy_preview(proxy1.get("chat_body")),
                    },
                    "proxy_exhausted": {
                        "mint_status": proxy2.get("mint_status"),
                        "chat_status": p2_status,
                        "error_code": p2_code,
                        "error_message": _err_msg(p2_body),
                        "body": p2_body,
                    },
                },
            )
        )
        if not ok5:
            _emit(results, meta, llm_turns_used)
            return 1

    meta["llm_turns_used"] = llm_turns_used
    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _emit(results, meta, llm_turns_used)
    return 0 if all(r.status == "PASS" for r in results) else 1


def _usage_month_nano(summary: dict[str, Any]) -> int:
    month = summary.get("month")
    if isinstance(month, dict):
        if isinstance(month.get("cost"), dict):
            return int(month["cost"].get("total") or 0)
        if "cost_total" in month:
            return int(month["cost_total"] or 0)
    for key in ("month_cost_total", "cost_total"):
        if key in summary:
            return int(summary[key] or 0)
    # deep search
    today = summary.get("today")
    if isinstance(today, dict) and isinstance(today.get("cost"), dict):
        # still prefer month; fall back today
        pass
    return 0


def _proxy_preview(body: Any) -> Any:
    if not isinstance(body, dict):
        return body
    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        msg = (choices[0] or {}).get("message") or {}
        return {"content": (msg.get("content") or "")[:80], "usage": body.get("usage")}
    return {"keys": list(body.keys()), "error": body.get("error")}


def _emit(results: list[CheckResult], meta: dict[str, Any], llm_turns: int) -> None:
    meta["llm_turns_used"] = llm_turns
    report = {
        "meta": meta,
        "checks": [asdict(r) for r in results],
        "verdict": (
            "PASS"
            if results and all(r.status == "PASS" for r in results if r.item >= 1)
            else "FAIL"
        ),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"free_tier_{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n# report written: {out}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
