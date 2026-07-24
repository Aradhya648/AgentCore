"""多人共享空间 v1 真实环境端到端验收探针（docs/02-架构/双模式工作区.md §十一 · 决策 1–4）。

扮演三个注册用户走完整生命周期，逐项独立断言并输出 PASS/FAIL。
不跑真实 LLM 回合；不改产品代码。发现缺陷时仍跑完全部检查项再汇总。

从 ``apps/server`` 跑::

    uv run python scripts/probe_shared_spaces.py
    uv run python scripts/probe_shared_spaces.py --base http://localhost:8000

产出 JSON 报告到 stdout，并写 ``logs/probes/shared_spaces_<ts>.json``。
自建带时间戳的测试用户与空间；结束时尽力删除本轮创建的共享空间（用户行保留）。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from agentcore.workspace.shared_paths import shared_workspace_root_path

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "logs" / "probes"
DEFAULT_BASE = os.environ.get("PROBE_BASE_URL", "http://localhost:8000")
PASSWORD = "ProbePass1!"
MAX_SPACES = 10


@dataclass
class CheckResult:
    item: int
    name: str
    status: str  # PASS | FAIL | SKIP
    evidence: dict[str, Any] = field(default_factory=dict)
    note: str = ""


def _ts() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def _ws_files_url(base: str, ws_id: str, path: str | None = None) -> str:
    enc = quote(ws_id, safe="")
    if path is None:
        return f"{base}/v1/workspaces/{enc}/files"
    return f"{base}/v1/workspaces/{enc}/files/{quote(path, safe='/')}"


async def _register(
    client: httpx.AsyncClient, base: str, username: str
) -> dict[str, Any]:
    r = await client.post(
        f"{base}/v1/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "display_name": f"SS Probe {username}",
        },
    )
    r.raise_for_status()
    return r.json()


async def _login(client: httpx.AsyncClient, base: str, username: str) -> str:
    r = await client.post(
        f"{base}/v1/auth/token",
        json={"username": username, "password": PASSWORD},
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def _json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    token: str,
    **kwargs: Any,
) -> tuple[int, Any]:
    r = await client.request(method, url, headers=_hdr(token), **kwargs)
    try:
        body: Any = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


class FirehoseCollector:
    """Background SSE reader for ``GET /v1/realtime``."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.error: str | None = None

    def start(self, client: httpx.AsyncClient, base: str, token: str) -> None:
        self._task = asyncio.create_task(self._run(client, base, token))

    async def _run(self, client: httpx.AsyncClient, base: str, token: str) -> None:
        try:
            async with client.stream(
                "GET",
                f"{base}/v1/realtime",
                headers=_hdr(token),
                timeout=httpx.Timeout(None, connect=30.0),
            ) as resp:
                if resp.status_code != 200:
                    self.error = f"firehose status={resp.status_code}"
                    self.ready.set()
                    return
                buf = ""
                async for chunk in resp.aiter_text():
                    if self._stop.is_set():
                        return
                    buf += chunk
                    while "\n\n" in buf:
                        frame, buf = buf.split("\n\n", 1)
                        event_type = "message"
                        data_lines: list[str] = []
                        for line in frame.splitlines():
                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                            elif line.startswith("data:"):
                                data_lines.append(line[5:].lstrip())
                        if not data_lines:
                            continue
                        raw = "\n".join(data_lines)
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            payload = {"raw": raw}
                        if not isinstance(payload, dict):
                            payload = {"raw": payload}
                        payload.setdefault("type", event_type)
                        self.events.append(payload)
                        if payload.get("type") == "ready":
                            self.ready.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — probe must keep going
            self.error = str(exc)
            self.ready.set()

    async def wait_ready(self, timeout: float = 10.0) -> bool:
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=timeout)
            return self.error is None
        except TimeoutError:
            self.error = self.error or "firehose ready timeout"
            return False

    async def wait_for(
        self, event_type: str, *, timeout: float = 15.0, since: int = 0
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for ev in self.events[since:]:
                if ev.get("type") == event_type:
                    return ev
            await asyncio.sleep(0.1)
        return None

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


def _emit(results: list[CheckResult], meta: dict[str, Any]) -> None:
    fail_items = [r.item for r in results if r.status == "FAIL"]
    skip_items = [r.item for r in results if r.status == "SKIP"]
    report = {
        "meta": meta,
        "checks": [asdict(r) for r in results],
        "verdict": "FAIL" if fail_items else "PASS",
        "fail_items": fail_items,
        "skip_items": skip_items,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"shared_spaces_{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\n# report written: {out}", file=sys.stderr)

    # Human-readable checklist
    print("\n===== 验收清单 =====", file=sys.stderr)
    for r in results:
        line = f"[{r.status}] #{r.item} {r.name}"
        if r.note:
            line += f" — {r.note}"
        print(line, file=sys.stderr)
    print(f"VERDICT: {report['verdict']}", file=sys.stderr)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Shared spaces v1 E2E probe")
    parser.add_argument("--base", default=DEFAULT_BASE, help="API base URL")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    stamp = _ts()
    user_a = f"ss_a_{stamp}"
    user_b = f"ss_b_{stamp}"
    user_c = f"ss_c_{stamp}"

    meta: dict[str, Any] = {
        "probe": "shared_spaces",
        "base": base,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "users": {"a": user_a, "b": user_b, "c": user_c},
    }
    results: list[CheckResult] = []
    created_space_ids: list[str] = []
    main_space_id: str | None = None
    main_ws_id: str | None = None
    user_ids: dict[str, str] = {}
    firehose = FirehoseCollector()

    timeout = httpx.Timeout(60.0, connect=15.0)
    # Separate long-lived client for firehose so short requests aren't blocked.
    async with (
        httpx.AsyncClient(timeout=timeout) as client,
        httpx.AsyncClient(timeout=httpx.Timeout(None, connect=15.0)) as fh_client,
    ):
        # --- bootstrap users ---
        try:
            ra = await _register(client, base, user_a)
            rb = await _register(client, base, user_b)
            rc = await _register(client, base, user_c)
            user_ids = {
                "a": ra.get("id") or ra.get("user_id") or "",
                "b": rb.get("id") or rb.get("user_id") or "",
                "c": rc.get("id") or rc.get("user_id") or "",
            }
            # register may not return id — fetch via /v1/users/me
            tok_a = await _login(client, base, user_a)
            tok_b = await _login(client, base, user_b)
            tok_c = await _login(client, base, user_c)
            for label, tok in (("a", tok_a), ("b", tok_b), ("c", tok_c)):
                st, me = await _json(client, "GET", f"{base}/v1/users/me", token=tok)
                if st == 200 and isinstance(me, dict):
                    user_ids[label] = me.get("id") or user_ids[label]
            meta["user_ids"] = user_ids
        except Exception as exc:  # noqa: BLE001
            meta["bootstrap_error"] = str(exc)
            results.append(
                CheckResult(0, "bootstrap 注册登录", "FAIL", note=str(exc))
            )
            meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _emit(results, meta)
            return 1

        # Firehose for B — open before invites / writes (item 8)
        firehose.start(fh_client, base, tok_b)
        fh_ok = await firehose.wait_ready(timeout=12.0)
        meta["firehose_ready"] = fh_ok
        if firehose.error:
            meta["firehose_error"] = firehose.error

        # ========== 1. create + quota ==========
        created: list[dict[str, Any]] = []
        quota_status = None
        quota_body: Any = None
        try:
            for i in range(MAX_SPACES):
                st, body = await _json(
                    client,
                    "POST",
                    f"{base}/v1/shared-spaces",
                    token=tok_a,
                    json={"name": f"probe-space-{i}-{stamp}"},
                )
                if st in (200, 201) and isinstance(body, dict):
                    created.append(body)
                    created_space_ids.append(body["id"])
                else:
                    break
            st11, body11 = await _json(
                client,
                "POST",
                f"{base}/v1/shared-spaces",
                token=tok_a,
                json={"name": f"probe-overflow-{stamp}"},
            )
            quota_status, quota_body = st11, body11
            if isinstance(body11, dict) and body11.get("id"):
                created_space_ids.append(body11["id"])

            ok1 = (
                len(created) == MAX_SPACES
                and quota_status == 429
                and _err_code(quota_body) == "QUOTA_EXCEEDED"
            )

            results.append(
                CheckResult(
                    1,
                    "用户 A 建共享空间；超出资源上限（10）被拒",
                    "PASS" if ok1 else "FAIL",
                    evidence={
                        "created_count": len(created),
                        "overflow_status": quota_status,
                        "overflow_code": _err_code(quota_body),
                        "overflow_message": _err_msg(quota_body),
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(1, "用户 A 建共享空间；超出资源上限（10）被拒", "FAIL", note=str(exc))
            )

        # Keep one main space; delete extras so later steps aren't noisy
        if created:
            main = created[0]
            main_space_id = main["id"]
            main_ws_id = main.get("ws_id") or f"shared:{main_space_id}"
            for extra in created[1:]:
                await _json(
                    client,
                    "DELETE",
                    f"{base}/v1/shared-spaces/{extra['id']}",
                    token=tok_a,
                )
                if extra["id"] in created_space_ids:
                    created_space_ids.remove(extra["id"])
        else:
            st, body = await _json(
                client,
                "POST",
                f"{base}/v1/shared-spaces",
                token=tok_a,
                json={"name": f"probe-main-{stamp}"},
            )
            if st in (200, 201) and isinstance(body, dict):
                main_space_id = body["id"]
                main_ws_id = body.get("ws_id") or f"shared:{main_space_id}"
                created_space_ids.append(main_space_id)

        assert main_space_id and main_ws_id
        meta["main_space_id"] = main_space_id
        meta["main_ws_id"] = main_ws_id
        fh_before_invite = len(firehose.events)

        # ========== 2. search + invite + pending ==========
        try:
            st_s, body_s = await _json(
                client,
                "GET",
                f"{base}/v1/messages/users/search",
                token=tok_a,
                params={"q": user_b},
            )
            hits = body_s.get("data") if isinstance(body_s, dict) else None
            found_b = False
            b_id = user_ids.get("b") or ""
            if isinstance(hits, list):
                for h in hits:
                    if h.get("username") == user_b or h.get("id") == b_id:
                        found_b = True
                        b_id = h.get("id") or b_id
                        break

            st_inv, body_inv = await _json(
                client,
                "POST",
                f"{base}/v1/shared-spaces/{main_space_id}/invites",
                token=tok_a,
                json={"user_id": b_id, "role": "editor"},
            )
            st_p, body_p = await _json(
                client,
                "GET",
                f"{base}/v1/shared-spaces/invites/pending",
                token=tok_b,
            )
            pending = body_p.get("data") if isinstance(body_p, dict) else []
            pending_ids = [p.get("id") for p in pending] if isinstance(pending, list) else []

            ok2 = (
                st_s == 200
                and found_b
                and st_inv in (200, 201)
                and isinstance(body_inv, dict)
                and body_inv.get("role") == "editor"
                and body_inv.get("state") == "pending"
                and main_space_id in pending_ids
            )
            results.append(
                CheckResult(
                    2,
                    "A 精确搜人找到 B → 定向邀请（editor）；B pending 可见",
                    "PASS" if ok2 else "FAIL",
                    evidence={
                        "search_status": st_s,
                        "found_b": found_b,
                        "invite_status": st_inv,
                        "invite_body": body_inv,
                        "pending_status": st_p,
                        "pending_ids": pending_ids,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    2,
                    "A 精确搜人找到 B → 定向邀请（editor）；B pending 可见",
                    "FAIL",
                    note=str(exc),
                )
            )

        invite_ev = await firehose.wait_for(
            "shared_space_invite", timeout=8.0, since=fh_before_invite
        )

        # ========== 3. accept + C 404 ==========
        try:
            st_acc, body_acc = await _json(
                client,
                "POST",
                f"{base}/v1/shared-spaces/{main_space_id}/invites/accept",
                token=tok_b,
            )
            st_la, body_la = await _json(
                client, "GET", f"{base}/v1/shared-spaces", token=tok_a
            )
            st_lb, body_lb = await _json(
                client, "GET", f"{base}/v1/shared-spaces", token=tok_b
            )
            ids_a = [x["id"] for x in (body_la.get("data") or [])] if isinstance(body_la, dict) else []
            ids_b = [x["id"] for x in (body_lb.get("data") or [])] if isinstance(body_lb, dict) else []

            surfaces: dict[str, int] = {}
            for name, method, url in (
                ("get", "GET", f"{base}/v1/shared-spaces/{main_space_id}"),
                ("members", "GET", f"{base}/v1/shared-spaces/{main_space_id}/members"),
                ("events", "GET", f"{base}/v1/shared-spaces/{main_space_id}/events"),
                ("files", "GET", _ws_files_url(base, main_ws_id)),
            ):
                st_c, _ = await _json(client, method, url, token=tok_c)
                surfaces[name] = st_c

            ok3 = (
                st_acc == 200
                and main_space_id in ids_a
                and main_space_id in ids_b
                and all(v == 404 for v in surfaces.values())
            )
            results.append(
                CheckResult(
                    3,
                    "B 接受 → 双方列表可见；C 访问一律 404",
                    "PASS" if ok3 else "FAIL",
                    evidence={
                        "accept_status": st_acc,
                        "accept_role": body_acc.get("my_role") if isinstance(body_acc, dict) else None,
                        "a_list_has": main_space_id in ids_a,
                        "b_list_has": main_space_id in ids_b,
                        "c_surfaces": surfaces,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(3, "B 接受 → 双方列表可见；C 访问一律 404", "FAIL", note=str(exc))
            )

        fh_before_write = len(firehose.events)

        # ========== 4. file R/W both ways ==========
        try:
            content_a = f"hello-from-a-{stamp}"
            content_b = f"hello-from-b-{stamp}"
            r_wa = await client.put(
                _ws_files_url(base, main_ws_id, "from_a.txt"),
                headers={**_hdr(tok_a), "Content-Type": "application/octet-stream"},
                content=content_a.encode("utf-8"),
            )

            r_lb = await client.get(
                _ws_files_url(base, main_ws_id),
                headers=_hdr(tok_b),
                params={"recursive": "true"},
            )
            st_list_b = r_lb.status_code
            list_b = r_lb.json() if st_list_b == 200 else r_lb.text
            paths_b = []
            if isinstance(list_b, dict):
                paths_b = [e.get("path") or e.get("name") for e in (list_b.get("data") or [])]

            r_rb = await client.get(
                _ws_files_url(base, main_ws_id, "from_a.txt"),
                headers=_hdr(tok_b),
            )
            read_b = r_rb.content.decode("utf-8", errors="replace") if r_rb.status_code == 200 else None

            r_wb = await client.put(
                _ws_files_url(base, main_ws_id, "from_b.txt"),
                headers={**_hdr(tok_b), "Content-Type": "application/octet-stream"},
                content=content_b.encode("utf-8"),
            )
            r_ra = await client.get(
                _ws_files_url(base, main_ws_id, "from_b.txt"),
                headers=_hdr(tok_a),
            )
            read_a = r_ra.content.decode("utf-8", errors="replace") if r_ra.status_code == 200 else None

            ok4 = (
                r_wa.status_code in (200, 201)
                and r_rb.status_code == 200
                and read_b == content_a
                and r_wb.status_code in (200, 201)
                and r_ra.status_code == 200
                and read_a == content_b
                and any(p and "from_a" in str(p) for p in paths_b)
            )
            results.append(
                CheckResult(
                    4,
                    "A 写文件 → B 可读；B（editor）写 → A 可读",
                    "PASS" if ok4 else "FAIL",
                    evidence={
                        "a_write": r_wa.status_code,
                        "b_list_status": st_list_b,
                        "b_paths": paths_b,
                        "b_read_a": read_b,
                        "b_write": r_wb.status_code,
                        "a_read_b": read_a,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(4, "A 写文件 → B 可读；B（editor）写 → A 可读", "FAIL", note=str(exc))
            )

        changed_ev = await firehose.wait_for(
            "shared_space_changed", timeout=8.0, since=fh_before_write
        )

        # ========== 5. demote to viewer ==========
        try:
            st_role, body_role = await _json(
                client,
                "PATCH",
                f"{base}/v1/shared-spaces/{main_space_id}/members/{user_ids['b']}",
                token=tok_a,
                json={"role": "viewer"},
            )
            r_deny = await client.put(
                _ws_files_url(base, main_ws_id, "viewer_should_fail.txt"),
                headers={**_hdr(tok_b), "Content-Type": "application/octet-stream"},
                content=b"nope",
            )
            r_still = await client.get(
                _ws_files_url(base, main_ws_id, "from_a.txt"),
                headers=_hdr(tok_b),
            )
            still_ok = (
                r_still.status_code == 200
                and r_still.content.decode("utf-8", errors="replace").startswith("hello-from-a")
            )
            write_denied = r_deny.status_code in (403, 409, 422)
            ok5 = (
                st_role == 200
                and isinstance(body_role, dict)
                and body_role.get("role") == "viewer"
                and write_denied
                and still_ok
            )
            results.append(
                CheckResult(
                    5,
                    "A 把 B 降为 viewer → B 写被拒、仍可读（即时）",
                    "PASS" if ok5 else "FAIL",
                    evidence={
                        "role_status": st_role,
                        "role": body_role.get("role") if isinstance(body_role, dict) else None,
                        "write_status": r_deny.status_code,
                        "write_code": _err_code(
                            r_deny.json()
                            if r_deny.headers.get("content-type", "").startswith("application/json")
                            else {}
                        ),
                        "write_message": _err_msg(
                            r_deny.json()
                            if r_deny.headers.get("content-type", "").startswith("application/json")
                            else {}
                        ),
                        "read_status": r_still.status_code,
                        "still_readable": still_ok,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    5,
                    "A 把 B 降为 viewer → B 写被拒、仍可读（即时）",
                    "FAIL",
                    note=str(exc),
                )
            )

        # ========== 6. mounts ==========
        try:
            # Promote B back to editor for write-mode mount check on A, then re-check viewer mode
            await _json(
                client,
                "PATCH",
                f"{base}/v1/shared-spaces/{main_space_id}/members/{user_ids['b']}",
                token=tok_a,
                json={"role": "editor"},
            )

            st_ca, body_ca = await _json(
                client,
                "POST",
                f"{base}/v1/conversations",
                token=tok_a,
                json={"title": f"ss-mount-a-{stamp}"},
            )
            st_cb, body_cb = await _json(
                client,
                "POST",
                f"{base}/v1/conversations",
                token=tok_b,
                json={"title": f"ss-mount-b-{stamp}"},
            )
            conv_a = body_ca.get("id") if isinstance(body_ca, dict) else None
            conv_b = body_cb.get("id") if isinstance(body_cb, dict) else None

            st_ma, body_ma = await _json(
                client,
                "POST",
                f"{base}/v1/conversations/{conv_a}/workspace/shared-mounts",
                token=tok_a,
                json={"space_id": main_space_id},
            )
            mode_a = (
                (body_ma.get("mount") or {}).get("mode")
                if isinstance(body_ma, dict)
                else None
            )

            # B as editor → write
            st_mb_ed, body_mb_ed = await _json(
                client,
                "POST",
                f"{base}/v1/conversations/{conv_b}/workspace/shared-mounts",
                token=tok_b,
                json={"space_id": main_space_id},
            )
            mode_b_ed = (
                (body_mb_ed.get("mount") or {}).get("mode")
                if isinstance(body_mb_ed, dict)
                else None
            )
            # clear then demote and remount as viewer
            await _json(
                client,
                "DELETE",
                f"{base}/v1/conversations/{conv_b}/workspace/shared-mounts",
                token=tok_b,
            )
            await _json(
                client,
                "PATCH",
                f"{base}/v1/shared-spaces/{main_space_id}/members/{user_ids['b']}",
                token=tok_a,
                json={"role": "viewer"},
            )
            st_mb_v, body_mb_v = await _json(
                client,
                "POST",
                f"{base}/v1/conversations/{conv_b}/workspace/shared-mounts",
                token=tok_b,
                json={"space_id": main_space_id},
            )
            mode_b_v = (
                (body_mb_v.get("mount") or {}).get("mode")
                if isinstance(body_mb_v, dict)
                else None
            )

            # Local-bound mount rejection: bind fake root then mount
            local_note = ""
            local_status: int | None = None
            local_skip = False
            st_bind, body_bind = await _json(
                client,
                "PUT",
                f"{base}/v1/conversations/{conv_a}/workspace/binding",
                token=tok_a,
                json={"root_id": f"probe-local-root-{stamp}"},
            )
            if st_bind not in (200, 201):
                local_skip = True
                local_note = (
                    f"无法建立本地绑定（status={st_bind}）；跳过本地挂载拒测"
                )
            else:
                # revoke prior mounts then try mount on local-bound conv
                await _json(
                    client,
                    "DELETE",
                    f"{base}/v1/conversations/{conv_a}/workspace/shared-mounts",
                    token=tok_a,
                )
                st_local, body_local = await _json(
                    client,
                    "POST",
                    f"{base}/v1/conversations/{conv_a}/workspace/shared-mounts",
                    token=tok_a,
                    json={"space_id": main_space_id},
                )
                local_status = st_local
                if st_local not in (409, 400, 422):
                    local_note = (
                        f"本地绑定后挂载未拒：status={st_local} body={body_local}"
                    )
                # unbind to leave clean
                await _json(
                    client,
                    "DELETE",
                    f"{base}/v1/conversations/{conv_a}/workspace/binding",
                    token=tok_a,
                )

            cloud_ok = (
                st_ma in (200, 201)
                and mode_a == "write"
                and st_mb_ed in (200, 201)
                and mode_b_ed == "write"
                and st_mb_v in (200, 201)
                and mode_b_v == "readonly"
            )
            if local_skip:
                status6 = "PASS" if cloud_ok else "FAIL"
                # partial skip noted
                note6 = local_note
                if cloud_ok:
                    note6 = (local_note + "；云挂载部分 PASS").strip("；")
            else:
                local_ok = local_status in (409, 400, 422)
                status6 = "PASS" if (cloud_ok and local_ok) else "FAIL"
                note6 = local_note

            results.append(
                CheckResult(
                    6,
                    "云对话挂载成功且模式随角色；本地绑定挂载被拒",
                    status6,
                    evidence={
                        "conv_a": conv_a,
                        "conv_b": conv_b,
                        "mount_a": {"status": st_ma, "mode": mode_a},
                        "mount_b_editor": {"status": st_mb_ed, "mode": mode_b_ed},
                        "mount_b_viewer": {"status": st_mb_v, "mode": mode_b_v},
                        "bind_status": st_bind,
                        "local_mount_status": local_status,
                        "local_skip": local_skip,
                    },
                    note=note6,
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    6,
                    "云对话挂载成功且模式随角色；本地绑定挂载被拒",
                    "FAIL",
                    note=str(exc),
                )
            )

        # ========== 7. events ledger ==========
        try:
            st_ev, body_ev = await _json(
                client,
                "GET",
                f"{base}/v1/shared-spaces/{main_space_id}/events",
                token=tok_a,
                params={"limit": 100},
            )
            events = body_ev.get("data") if isinstance(body_ev, dict) else []
            actions = [e.get("action") for e in events] if isinstance(events, list) else []
            has_accept = "member_accepted" in actions
            has_role = "member_role_changed" in actions
            has_created = "space_created" in actions
            has_invited = "member_invited" in actions
            has_file = "file_written" in actions
            a_wrote = any(
                e.get("action") == "file_written" and e.get("actor_user_id") == user_ids["a"]
                for e in events
                if isinstance(e, dict)
            )
            b_wrote = any(
                e.get("action") == "file_written" and e.get("actor_user_id") == user_ids["b"]
                for e in events
                if isinstance(e, dict)
            )
            ok7 = (
                st_ev == 200
                and has_created
                and has_invited
                and has_accept
                and has_file
                and has_role
                and a_wrote
                and b_wrote
            )
            results.append(
                CheckResult(
                    7,
                    "变更流水 events 含关键操作且 actor 归因正确",
                    "PASS" if ok7 else "FAIL",
                    evidence={
                        "status": st_ev,
                        "actions": actions,
                        "has": {
                            "created": has_created,
                            "invited": has_invited,
                            "accept": has_accept,
                            "file": has_file,
                            "role": has_role,
                            "a_wrote": a_wrote,
                            "b_wrote": b_wrote,
                        },
                        "sample": events[:8] if isinstance(events, list) else events,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    7,
                    "变更流水 events 含关键操作且 actor 归因正确",
                    "FAIL",
                    note=str(exc),
                )
            )

        # ========== 8. firehose ==========
        try:
            invite_ok = (
                invite_ev is not None
                and invite_ev.get("space_id") == main_space_id
            )
            changed_ok = changed_ev is not None and changed_ev.get("space_id") == main_space_id
            types_seen = sorted({e.get("type") for e in firehose.events if e.get("type")})
            ok8 = fh_ok and invite_ok and changed_ok
            results.append(
                CheckResult(
                    8,
                    "firehose：B 收到 shared_space_invite 与 shared_space_changed",
                    "PASS" if ok8 else "FAIL",
                    evidence={
                        "firehose_ready": fh_ok,
                        "firehose_error": firehose.error,
                        "types_seen": types_seen,
                        "invite_event": invite_ev,
                        "changed_event": changed_ev,
                        "event_count": len(firehose.events),
                    },
                    note="" if fh_ok else "firehose 未就绪（同进程 hub 依赖）",
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    8,
                    "firehose：B 收到 shared_space_invite 与 shared_space_changed",
                    "FAIL",
                    note=str(exc),
                )
            )

        # ========== 9. block linkage ==========
        try:
            # Fresh space owned by C; invite B (pending); B blocks C → pending gone;
            # C invite again → rejected.
            st_sc, body_sc = await _json(
                client,
                "POST",
                f"{base}/v1/shared-spaces",
                token=tok_c,
                json={"name": f"probe-block-{stamp}"},
            )
            space_c = body_sc.get("id") if isinstance(body_sc, dict) else None
            if space_c:
                created_space_ids.append(space_c)

            st_inv1, _ = await _json(
                client,
                "POST",
                f"{base}/v1/shared-spaces/{space_c}/invites",
                token=tok_c,
                json={"user_id": user_ids["b"], "role": "viewer"},
            )
            st_p1, body_p1 = await _json(
                client,
                "GET",
                f"{base}/v1/shared-spaces/invites/pending",
                token=tok_b,
            )
            pending1 = [
                p.get("id")
                for p in (body_p1.get("data") or [])
                if isinstance(body_p1, dict)
            ]

            st_blk, body_blk = await _json(
                client,
                "POST",
                f"{base}/v1/messages/blocks",
                token=tok_b,
                json={"user_id": user_ids["c"]},
            )
            st_p2, body_p2 = await _json(
                client,
                "GET",
                f"{base}/v1/shared-spaces/invites/pending",
                token=tok_b,
            )
            pending2 = [
                p.get("id")
                for p in (body_p2.get("data") or [])
                if isinstance(body_p2, dict)
            ]

            st_inv2, body_inv2 = await _json(
                client,
                "POST",
                f"{base}/v1/shared-spaces/{space_c}/invites",
                token=tok_c,
                json={"user_id": user_ids["b"], "role": "viewer"},
            )

            # Also: B remains member of main_space (accepted) — block must NOT kick
            st_still, body_still = await _json(
                client,
                "GET",
                f"{base}/v1/shared-spaces/{main_space_id}",
                token=tok_b,
            )

            ok9 = (
                st_sc in (200, 201)
                and st_inv1 in (200, 201)
                and space_c in pending1
                and st_blk == 200
                and space_c not in pending2
                and st_inv2 in (400, 403, 404, 409, 422)
                and st_still == 200
            )
            results.append(
                CheckResult(
                    9,
                    "拉黑联动：挡新邀请 + 自动拒 pending；不踢已有成员",
                    "PASS" if ok9 else "FAIL",
                    evidence={
                        "space_c": space_c,
                        "invite1": st_inv1,
                        "pending_before": pending1,
                        "block_status": st_blk,
                        "pending_after": pending2,
                        "invite2_status": st_inv2,
                        "invite2_code": _err_code(body_inv2),
                        "invite2_message": _err_msg(body_inv2),
                        "b_still_member_of_main": st_still == 200,
                        "main_role": body_still.get("my_role")
                        if isinstance(body_still, dict)
                        else None,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    9,
                    "拉黑联动：挡新邀请 + 自动拒 pending；不踢已有成员",
                    "FAIL",
                    note=str(exc),
                )
            )

        # ========== 10. delete cascade ==========
        try:
            disk_before = shared_workspace_root_path(main_space_id)
            existed_before = disk_before.is_dir()
            st_del, body_del = await _json(
                client,
                "DELETE",
                f"{base}/v1/shared-spaces/{main_space_id}",
                token=tok_a,
            )
            st_lb, body_lb = await _json(
                client, "GET", f"{base}/v1/shared-spaces", token=tok_b
            )
            ids_b = [
                x["id"] for x in (body_lb.get("data") or [])
            ] if isinstance(body_lb, dict) else []
            st_get_b, _ = await _json(
                client,
                "GET",
                f"{base}/v1/shared-spaces/{main_space_id}",
                token=tok_b,
            )
            st_get_a, _ = await _json(
                client,
                "GET",
                f"{base}/v1/shared-spaces/{main_space_id}",
                token=tok_a,
            )
            st_files, _ = await _json(
                client,
                "GET",
                _ws_files_url(base, main_ws_id),
                token=tok_b,
            )
            disk_after_exists = disk_before.exists()
            # small settle for FS
            await asyncio.sleep(0.2)
            disk_after_exists = disk_before.exists()

            ok10 = (
                st_del == 200
                and main_space_id not in ids_b
                and st_get_b == 404
                and st_get_a == 404
                and st_files == 404
                and (not existed_before or not disk_after_exists)
            )
            results.append(
                CheckResult(
                    10,
                    "删除级联：B 列表消失、访问 404、磁盘目录清理",
                    "PASS" if ok10 else "FAIL",
                    evidence={
                        "delete_status": st_del,
                        "b_list_has": main_space_id in ids_b,
                        "get_b": st_get_b,
                        "get_a": st_get_a,
                        "files_b": st_files,
                        "disk_before": str(disk_before),
                        "disk_existed_before": existed_before,
                        "disk_exists_after": disk_after_exists,
                    },
                )
            )
            if main_space_id in created_space_ids:
                created_space_ids.remove(main_space_id)
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    10,
                    "删除级联：B 列表消失、访问 404、磁盘目录清理",
                    "FAIL",
                    note=str(exc),
                )
            )

        # cleanup remaining spaces (C's block space etc.)
        for sid in list(created_space_ids):
            for tok in (tok_a, tok_c):
                st, _ = await _json(
                    client, "DELETE", f"{base}/v1/shared-spaces/{sid}", token=tok
                )
                if st == 200:
                    break

        await firehose.stop()

    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _emit(results, meta)
    return 0 if all(r.status in ("PASS", "SKIP") for r in results) and not any(
        r.status == "FAIL" for r in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
