"""Continue free-tier C acceptance: item 4 title proof + item 5 proxy.

Uses existing users from the prior probe run so we stay within the ≤6 LLM budget.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from agentcore.db import async_session_factory
from agentcore.db.repositories import UserRepository

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "logs" / "probes"
LOG_PATH = REPO_ROOT / "logs" / "dev.jsonl"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
BASE = os.environ.get("PROBE_BASE_URL", "http://localhost:8000").rstrip("/")

FREE_USER = "ft_free_20260714025243"
BYOK_USER = "ft_byok_20260714025243"
PW = "TestPass1!"


def _load_dotenv() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


async def _login(client: httpx.AsyncClient, user: str) -> str:
    r = await client.post(f"{BASE}/v1/auth/token", json={"username": user, "password": PW})
    r.raise_for_status()
    return r.json()["access_token"]


async def _create_conv_empty_title(client: httpx.AsyncClient, token: str) -> str:
    # Empty title so background title mint runs (skips when title already set).
    r = await client.post(
        f"{BASE}/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": ""},
    )
    r.raise_for_status()
    return r.json()["id"]


async def _send(
    client: httpx.AsyncClient, token: str, conv_id: str, content: str
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    start = time.monotonic()
    async with client.stream(
        "POST",
        f"{BASE}/v1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": content},
    ) as resp:
        status = resp.status_code
        if status != 200:
            body = (await resp.aread()).decode("utf-8", "replace")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"raw": body}
            return {"http_status": status, "ok": False, "error_body": parsed, "message_id": None}
        async for line in resp.aiter_lines():
            if time.monotonic() - start > 180:
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
    mid = None
    finish = None
    err = None
    for ev in events:
        p = ev.get("payload") or {}
        if ev.get("type") == "message_start":
            mid = p.get("message_id") or mid
        if ev.get("type") == "message_end":
            mid = p.get("message_id") or mid
            finish = p.get("finish_reason")
        if ev.get("type") == "error":
            err = p
    return {
        "http_status": status,
        "ok": status == 200 and finish and not err,
        "message_id": mid,
        "finish_reason": finish,
        "error": err,
    }


def _llm_calls_for_user(user_id: str, *, scenario: str | None = None) -> list[dict[str, Any]]:
    if not LOG_PATH.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]:
        if user_id not in line:
            continue
        if '"event": "llm.call"' not in line:
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
                "timestamp": obj.get("timestamp"),
                "scenario": obj.get("scenario"),
                "cost_nano": obj.get("cost_nano"),
                "model": obj.get("model"),
                "credential_source": obj.get("credential_source"),
                "user_id": obj.get("user_id"),
                "input_tokens": obj.get("input_tokens"),
                "output_tokens": obj.get("output_tokens"),
            }
        )
    return rows


def _wait_title(user_id: str, before_n: int, deadline_s: float = 60.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        time.sleep(1.5)
        cur = _llm_calls_for_user(user_id, scenario="title")
        if len(cur) > before_n:
            return cur[-1]
    return None


async def _set_quota(username: str, monthly: float | None) -> str:
    async with async_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_username(username)
        assert user is not None
        await users.set_quota(user.user_id, monthly_cost_usd=monthly)
        user = await users.get_by_id(user.user_id)
        return f"monthly={user.quota_monthly_cost_usd!r}"


async def _user_id(username: str) -> str:
    async with async_session_factory() as session:
        u = await UserRepository(session).get_by_username(username)
        assert u is not None
        return str(u.user_id)


def _usage_month_nano(summary: dict[str, Any]) -> int:
    month = summary.get("month") or {}
    if isinstance(month.get("cost"), dict):
        return int(month["cost"].get("total") or 0)
    return int(month.get("cost_total") or 0)


def _err_code(body: Any) -> str | None:
    if isinstance(body, dict):
        err = body.get("error") or body
        if isinstance(err, dict):
            return err.get("code")
    return None


def _err_msg(body: Any) -> str | None:
    if isinstance(body, dict):
        err = body.get("error") or body
        if isinstance(err, dict):
            return err.get("message")
    return None


async def _proxy(client: httpx.AsyncClient, token: str, prompt: str) -> dict[str, Any]:
    mint = await client.post(
        f"{BASE}/v1/inference/token", headers={"Authorization": f"Bearer {token}"}
    )
    if mint.status_code != 200:
        try:
            body = mint.json()
        except Exception:
            body = {"raw": mint.text[:300]}
        return {"mint_status": mint.status_code, "mint_body": body, "chat_status": None}
    mj = mint.json()
    chat = await client.post(
        f"{BASE}/v1/inference/v1/chat/completions",
        headers={"Authorization": f"Bearer {mj['token']}"},
        json={
            "model": mj.get("model") or "deepseek-v4-flash",
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 32,
        },
    )
    try:
        cb = chat.json()
    except Exception:
        cb = {"raw": chat.text[:300]}
    return {
        "mint_status": 200,
        "model": mj.get("model"),
        "chat_status": chat.status_code,
        "chat_body": cb,
    }


async def main() -> int:
    byok_uid = await _user_id(BYOK_USER)
    free_uid = await _user_id(FREE_USER)
    # Ensure free user override cleared
    await _set_quota(FREE_USER, None)
    await _set_quota(BYOK_USER, None)

    title_before = _llm_calls_for_user(byok_uid, scenario="title")
    results: dict[str, Any] = {
        "prior_item4_partial": {
            "cost_total": 0,
            "tokens_recorded": True,
            "quota_low_still_200": True,
            "source": "free_tier_20260714-025347.json",
            "followups_already_cost0_user_key": [
                r
                for r in _llm_calls_for_user(byok_uid, scenario="followups")
                if r.get("cost_nano") == 0 and r.get("credential_source") == "user"
            ][-2:],
        }
    }

    timeout = httpx.Timeout(300.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        byok_tok = await _login(client, BYOK_USER)
        conv = await _create_conv_empty_title(client, byok_tok)
        turn = await _send(client, byok_tok, conv, "用一句话解释什么是储蓄")
        results["byok_title_trigger_turn"] = turn
        if not turn.get("ok"):
            results["item4"] = {"status": "FAIL", "reason": "title-trigger turn failed", "turn": turn}
            _write(results)
            return 1

        title_row = await asyncio.to_thread(_wait_title, byok_uid, len(title_before), 60.0)
        # also capture any background calls
        bg = [
            r
            for r in _llm_calls_for_user(byok_uid)
            if r.get("scenario") in {"title", "followups", "memory"}
            and r.get("timestamp", "") >= (title_row or {}).get("timestamp", "2026-07-13T18:52:00Z")
        ]
        ok4_title = (
            title_row is not None
            and int(title_row.get("cost_nano") or -1) == 0
            and title_row.get("credential_source") == "user"
        )
        results["item4"] = {
            "status": "PASS" if ok4_title else "FAIL",
            "title_llm_call": title_row,
            "background_calls_after": bg[-5:],
            "combined_with_prior": {
                "main_turn_cost_total": 0,
                "tokens_ok": True,
                "quota_low_second_turn_200": True,
                "configured": True,
                "free_tier_active": False,
            },
        }
        if not ok4_title:
            _write(results)
            return 1

        # ── item 5 proxy ──
        free_tok = await _login(client, FREE_USER)
        before = await client.get(
            f"{BASE}/v1/usage/summary", headers={"Authorization": f"Bearer {free_tok}"}
        )
        before.raise_for_status()
        before_j = before.json()
        before_nano = _usage_month_nano(before_j)

        proxy1 = await _proxy(client, free_tok, "用两字回答：你好")
        await asyncio.sleep(2.5)
        after = await client.get(
            f"{BASE}/v1/usage/summary", headers={"Authorization": f"Bearer {free_tok}"}
        )
        after.raise_for_status()
        after_j = after.json()
        after_nano = _usage_month_nano(after_j)

        await _set_quota(FREE_USER, 0.000001)
        proxy2 = await _proxy(client, free_tok, "ping")
        await _set_quota(FREE_USER, None)

        p2_status = proxy2.get("chat_status")
        p2_body = proxy2.get("chat_body") or proxy2.get("mint_body") or {}
        if p2_status is None and proxy2.get("mint_status") == 429:
            p2_status = 429
        p2_code = _err_code(p2_body)

        # DB proof for free user growth via proxy
        async with async_session_factory() as session:
            n_calls = (
                await session.execute(
                    text("SELECT COUNT(*) FROM cost_calls WHERE user_id=:u"),
                    {"u": free_uid},
                )
            ).scalar_one()

        ok5 = (
            proxy1.get("chat_status") == 200
            and after_nano > before_nano
            and p2_status == 429
            and p2_status != 402
            and p2_code == "FREE_TIER_EXHAUSTED"
        )
        results["item5"] = {
            "status": "PASS" if ok5 else "FAIL",
            "proxy_ok": {
                "chat_status": proxy1.get("chat_status"),
                "model": proxy1.get("model"),
                "usage_before_nano": before_nano,
                "usage_after_nano": after_nano,
                "grew": after_nano > before_nano,
                "chat_preview": _preview(proxy1.get("chat_body")),
                "cost_calls_user_total": int(n_calls),
            },
            "proxy_exhausted": {
                "mint_status": proxy2.get("mint_status"),
                "chat_status": p2_status,
                "error_code": p2_code,
                "error_message": _err_msg(p2_body),
                "body": p2_body,
            },
        }
        if not ok5:
            _write(results)
            return 1

    results["verdict"] = "PASS"
    _write(results)
    return 0


def _preview(body: Any) -> Any:
    if not isinstance(body, dict):
        return body
    choices = body.get("choices")
    if isinstance(choices, list) and choices:
        msg = (choices[0] or {}).get("message") or {}
        return {"content": (msg.get("content") or "")[:80], "usage": body.get("usage")}
    return {"keys": list(body.keys()), "error": body.get("error")}


def _write(results: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"free_tier_continue_{stamp}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n# written {out}", flush=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
