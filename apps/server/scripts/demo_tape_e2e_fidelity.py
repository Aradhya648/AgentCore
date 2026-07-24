"""E2E API fidelity: start tape, resume, compare content + fold vs oracle."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy import text

from agentcore.db.base import async_session_factory
from agentcore.runtime.journal.fold import runs_from_entries

ORACLE_MID = "69262466-c868-4f53-a6a2-6d626c5c0c19"
API = "http://127.0.0.1:8015"
OUT = Path(__file__).resolve().parents[3] / "apps" / "desktop" / "demo-tape-out"


async def oracle_content() -> str:
    async with async_session_factory() as s:
        return (
            await s.execute(text("SELECT content FROM messages WHERE id=:m"), {"m": ORACLE_MID})
        ).scalar_one() or ""


def graph_sig(events: list[dict]) -> dict:
    started = [e for e in events if e.get("type") == "run_started"]
    mods = [
        e
        for e in started
        if (p := e.get("payload") or {})
        and str(p.get("run_id", "")).startswith("debate_")
        and "_r" not in str(p.get("run_id"))
        and "_closing" not in str(p.get("run_id"))
        and "_cx_" not in str(p.get("run_id"))
        and p.get("kind") == "agent"
    ]
    closings = [
        e for e in started if "closing" in str((e.get("payload") or {}).get("run_id", ""))
    ]
    cx = sum(
        1
        for e in events
        if e.get("type") == "run_context"
        and any(
            b.get("channel") == "cross_exam"
            for b in ((e.get("payload") or {}).get("blocks") or [])
        )
    )
    closing_ctx = sum(
        1
        for e in events
        if e.get("type") == "run_context"
        and any(
            b.get("channel") == "closing"
            for b in ((e.get("payload") or {}).get("blocks") or [])
        )
    )
    out_d = sum(1 for e in events if e.get("type") == "run_output_delta")
    rounds = sum(1 for e in events if e.get("type") == "debate_round_started")
    return {
        "mods": len(mods),
        "closings": len(closings),
        "cx": cx,
        "closing_ctx": closing_ctx,
        "out_d": out_d,
        "rounds": rounds,
    }


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    oracle = await oracle_content()
    report: dict = {"errors": [], "checks": {}, "api": API}

    async with httpx.AsyncClient(base_url=API, timeout=300.0, follow_redirects=True) as c:
        await c.post("/v1/auth/login", json={"username": "dev", "password": "devpassword"})
        c.headers["X-CSRF-Token"] = c.cookies.get("csrf_token") or ""
        r = await c.post(
            "/v1/demo-tape/start",
            json={"tape_id": "lv-molihua-trademark", "speed": 80, "max_gap_ms": 50},
        )
        r.raise_for_status()
        cid = r.json()["conversation_id"]
        msgs = (await c.get(f"/v1/conversations/{cid}/messages")).json()["data"]
        asst = next(m for m in msgs if m.get("role") == "assistant")
        mid = asst["id"]
        rec = (await c.get(f"/v1/conversations/{cid}/recovery")).json()
        paused = (rec.get("paused") or [])[0]
        cp = paused["checkpoint_id"]
        print("resume", cid, mid, cp)
        async with c.stream(
            "POST",
            f"/v1/conversations/{cid}/messages/{mid}/resume",
            json={"checkpoint_id": cp, "decision": "continue", "note": ""},
        ) as resp:
            print("resume status", resp.status_code)
            async for _line in resp.aiter_lines():
                pass
            print("sse done")

    # SSE drain finished ⇒ turn settled; read final content from DB.
    async with async_session_factory() as s:
        content = (
            await s.execute(text("SELECT content FROM messages WHERE id=:m"), {"m": mid})
        ).scalar_one() or ""
    report["checks"]["content_byte_equal"] = content == oracle
    if content != oracle:
        report["errors"].append(f"content mismatch {len(content)} vs {len(oracle)}")
        for i, (a, b) in enumerate(zip(oracle, content, strict=False)):
            if a != b:
                report["first_diff"] = i
                break

    async with async_session_factory() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT kind, payload, ts FROM turn_journal WHERE turn_id=:m ORDER BY seq"
                ),
                {"m": mid},
            )
        ).mappings().all()
    entries = [
        {"kind": r["kind"], "payload": r["payload"] or {}, "ts": r["ts"]} for r in rows
    ]
    print("kinds", dict(Counter(e["kind"] for e in entries).most_common(15)))
    runs = runs_from_entries(entries)
    ev = (runs or {}).get("events") or []
    sig = graph_sig(ev)
    report["graph"] = sig
    report["checks"]["has_moderator"] = sig["mods"] >= 1
    report["checks"]["has_closing"] = sig["closings"] >= 2 and sig["closing_ctx"] >= 2
    report["checks"]["has_cross_exam"] = sig["cx"] >= 1
    report["checks"]["has_output_deltas"] = sig["out_d"] >= 10
    report["checks"]["has_rounds"] = sig["rounds"] >= 1

    first_s: dict[str, int] = {}
    first_c: dict[str, int] = {}
    for i, e in enumerate(ev):
        rid = str((e.get("payload") or {}).get("run_id") or "")
        if e.get("type") == "run_started" and rid not in first_s:
            first_s[rid] = i
        if e.get("type") == "run_context" and rid not in first_c:
            first_c[rid] = i
    bad = [rid for rid, ci in first_c.items() if rid in first_s and first_s[rid] > ci]
    report["checks"]["order_ok"] = not bad
    if bad:
        report["errors"].append(f"order bad {len(bad)}")

    for k, v in report["checks"].items():
        if not v:
            report["errors"].append(f"fail {k}")

    report["ok"] = not report["errors"]
    report["replay_cid"] = cid
    report["replay_mid"] = mid
    path = OUT / "e2e-fidelity-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote {path}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
