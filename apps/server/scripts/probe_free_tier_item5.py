"""Item 5 only: sidecar proxy free-tier path."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from agentcore.db import async_session_factory
from agentcore.db.repositories import UserRepository

BASE = "http://localhost:8000"
FREE_USER = "ft_free_20260714025243"
PW = "TestPass1!"
OUT = Path(__file__).resolve().parents[3] / "logs" / "probes"


async def _set_quota(username: str, monthly: float | None) -> None:
    async with async_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_username(username)
        assert user is not None
        await users.set_quota(user.user_id, monthly_cost_usd=monthly)


def _month_nano(summary: dict[str, Any]) -> int:
    month = summary.get("month") or {}
    if isinstance(month.get("cost"), dict):
        return int(month["cost"].get("total") or 0)
    return 0


def _code(body: Any) -> str | None:
    if isinstance(body, dict):
        err = body.get("error") or body
        if isinstance(err, dict):
            return err.get("code")
    return None


def _msg(body: Any) -> str | None:
    if isinstance(body, dict):
        err = body.get("error") or body
        if isinstance(err, dict):
            return err.get("message")
    return None


async def main() -> int:
    await _set_quota(FREE_USER, None)
    timeout = httpx.Timeout(120.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tok = (
            await client.post(
                f"{BASE}/v1/auth/token", json={"username": FREE_USER, "password": PW}
            )
        ).json()["access_token"]
        hdr = {"Authorization": f"Bearer {tok}"}

        before = (await client.get(f"{BASE}/v1/usage/summary", headers=hdr)).json()
        before_nano = _month_nano(before)

        # Sidecar always sends conversation attribution; without it spend is dropped
        # (inference.proxy_spend_no_conversation).
        async with async_session_factory() as session:
            users = UserRepository(session)
            u = await users.get_by_username(FREE_USER)
            assert u is not None
            uid = str(u.user_id)
            conv_id = (
                await session.execute(
                    text(
                        "SELECT id FROM conversations WHERE user_id=:u "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"u": uid},
                )
            ).scalar_one()
            conv_id = str(conv_id)

        mint = await client.post(f"{BASE}/v1/inference/token", headers=hdr)
        mint.raise_for_status()
        mj = mint.json()
        chat_hdr = {
            "Authorization": f"Bearer {mj['token']}",
            "X-AgentCore-Conversation": conv_id,
        }
        chat1 = await client.post(
            f"{BASE}/v1/inference/v1/chat/completions",
            headers=chat_hdr,
            json={
                "model": mj.get("model") or "deepseek-v4-flash",
                "stream": False,
                "messages": [{"role": "user", "content": "用两字回答：你好"}],
                "max_tokens": 32,
            },
        )
        try:
            body1 = chat1.json()
        except Exception:
            body1 = {"raw": chat1.text[:300]}

        await asyncio.sleep(3.5)
        after = (await client.get(f"{BASE}/v1/usage/summary", headers=hdr)).json()
        after_nano = _month_nano(after)

        await _set_quota(FREE_USER, 0.000001)
        mint2 = await client.post(f"{BASE}/v1/inference/token", headers=hdr)
        if mint2.status_code != 200:
            p2_status = mint2.status_code
            try:
                body2 = mint2.json()
            except Exception:
                body2 = {"raw": mint2.text[:300]}
            mint2_status = mint2.status_code
            chat2_status = None
        else:
            mint2_status = 200
            mj2 = mint2.json()
            chat2 = await client.post(
                f"{BASE}/v1/inference/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {mj2['token']}",
                    "X-AgentCore-Conversation": conv_id,
                },
                json={
                    "model": mj2.get("model") or "deepseek-v4-flash",
                    "stream": False,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 8,
                },
            )
            chat2_status = chat2.status_code
            p2_status = chat2_status
            try:
                body2 = chat2.json()
            except Exception:
                body2 = {"raw": chat2.text[:300]}
        await _set_quota(FREE_USER, None)

        async with async_session_factory() as session:
            n = (
                await session.execute(
                    text("SELECT COUNT(*) FROM cost_calls WHERE user_id=:u"),
                    {"u": uid},
                )
            ).scalar_one()

        preview = None
        if isinstance(body1, dict) and body1.get("choices"):
            preview = {
                "content": ((body1["choices"][0].get("message") or {}).get("content") or "")[:80],
                "usage": body1.get("usage"),
            }

        ok = (
            chat1.status_code == 200
            and after_nano > before_nano
            and p2_status == 429
            and p2_status != 402
            and _code(body2) == "FREE_TIER_EXHAUSTED"
        )
        report = {
            "item": 5,
            "status": "PASS" if ok else "FAIL",
            "proxy_ok": {
                "conversation_id": conv_id,
                "mint_model": mj.get("model"),
                "chat_status": chat1.status_code,
                "usage_before_nano": before_nano,
                "usage_after_nano": after_nano,
                "grew": after_nano > before_nano,
                "chat_preview": preview,
                "cost_calls_count": int(n),
            },
            "proxy_exhausted": {
                "mint_status": mint2_status,
                "chat_status": chat2_status,
                "http_status": p2_status,
                "error_code": _code(body2),
                "error_message": _msg(body2),
                "body": body2,
            },
        }
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"free_tier_item5_{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\n# written {path}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
