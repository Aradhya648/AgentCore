"""Probe M1 simulation: login → create run → advance 1 tick (real DeepSeek)."""

from __future__ import annotations

import asyncio
import os
import time

import httpx

API = os.environ.get("PROBE_BASE_URL", "http://localhost:8000").rstrip("/")
USER = os.environ.get("DEV_USERNAME", "dev")
PASS = os.environ.get("DEV_PASSWORD", "devpassword")


async def main() -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as c:
        r = await c.post(f"{API}/v1/auth/token", json={"username": USER, "password": PASS})
        r.raise_for_status()
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}", "X-Client-Platform": "desktop"}

        r = await c.post(f"{API}/v1/simulation/runs", headers=h, json={"scenario": "town", "seed": 7})
        print("create", r.status_code)
        r.raise_for_status()
        run_id = r.json()["id"]
        print("run_id", run_id)

        t0 = time.monotonic()
        r = await c.post(f"{API}/v1/simulation/runs/{run_id}/tick", headers=h, json={})
        elapsed = time.monotonic() - t0
        print("tick", r.status_code, f"elapsed={elapsed:.1f}s")
        if r.status_code != 200:
            print(r.text[:800])
            raise SystemExit(1)

        snap = r.json()["snapshot"]
        agents = snap.get("agents", {})
        print("agent_count", len(agents))
        for aid, st in sorted(agents.items()):
            act = (st.get("activity") or "")[:70]
            loc = st.get("location")
            print(f"  {aid} @ {loc} | {act}")
        events = snap.get("event_log", [])
        print("events", len(events))
        for ev in events[:8]:
            print(" ", ev[:100])


if __name__ == "__main__":
    asyncio.run(main())
