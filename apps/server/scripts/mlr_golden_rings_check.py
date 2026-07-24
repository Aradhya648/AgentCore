"""批 C · LV 案黄金场六环离线验收检查器。

对已跑完的会话做只读检查（DB turn_journal + messages.cost + 工作区文件），
不调 LLM、不打 HTTP、不占用 8000 端口、不改 .env。

Usage (apps/server)::

    uv run python scripts/mlr_golden_rings_check.py <conversation_id>
    uv run python scripts/mlr_golden_rings_check.py --trace <trace_id>
    uv run python scripts/mlr_golden_rings_check.py --json <conversation_id>
    uv run python scripts/mlr_golden_rings_check.py --fixture tests/fixtures/mlr_golden_ring6_positive.json

自测（不碰 DB）见 ``tests/test_mlr_golden_rings.py``。
真跑驱动（会调 LLM）仍可用已废弃验收职责的 ``_mlr_two_act_verify.py``。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from agentcore.conformance.mlr_golden_rings import (  # noqa: E402
    GoldenBundle,
    evaluate_rings,
    format_report,
)


async def _resolve_conversation_id(session: Any, raw: str) -> str:
    """Accept conversation UUID or 32-hex trace_id."""
    from sqlalchemy import text

    token = (raw or "").strip()
    if not token:
        raise SystemExit("missing conversation_id / trace_id")
    # UUID-ish → try conversations first
    row = (
        await session.execute(
            text("SELECT id FROM conversations WHERE id::text = :id LIMIT 1"),
            {"id": token},
        )
    ).first()
    if row:
        return str(row[0])
    # trace_id on messages
    hex32 = token.replace("-", "")
    if len(hex32) == 32:
        row = (
            await session.execute(
                text(
                    """
                    SELECT conversation_id
                    FROM messages
                    WHERE trace_id = :tid
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"tid": hex32},
            )
        ).first()
        if row and row[0]:
            return str(row[0])
    raise SystemExit(f"conversation / trace not found: {token!r}")


async def load_bundle_from_db(conversation_id: str) -> GoldenBundle:
    """只读装载：turn_journal + 首条用户原文 + messages.cost + 工作区文件列表。"""
    from sqlalchemy import text

    from agentcore.db import async_session_factory
    from agentcore.workspace.locate import workspace_root_path

    async with async_session_factory() as session:
        cid = await _resolve_conversation_id(session, conversation_id)
        conv = (
            await session.execute(
                text(
                    """
                    SELECT id, user_id, folder_id
                    FROM conversations
                    WHERE id = :cid
                    """
                ),
                {"cid": cid},
            )
        ).mappings().first()
        if not conv:
            raise SystemExit(f"conversation not found: {cid}")

        user_row = (
            await session.execute(
                text(
                    """
                    SELECT content
                    FROM messages
                    WHERE conversation_id = :cid AND role = 'user'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ),
                {"cid": cid},
            )
        ).first()
        user_prompt = str(user_row[0] or "") if user_row else ""

        journal_rows = (
            await session.execute(
                text(
                    """
                    SELECT turn_id, seq, kind, payload
                    FROM turn_journal
                    WHERE conversation_id = :cid
                    ORDER BY created_at ASC, turn_id ASC, seq ASC
                    """
                ),
                {"cid": cid},
            )
        ).mappings().all()

        cost_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, cost
                    FROM messages
                    WHERE conversation_id = :cid
                      AND role = 'assistant'
                      AND cost IS NOT NULL
                    """
                ),
                {"cid": cid},
            )
        ).mappings().all()

    events: list[dict[str, Any]] = []
    for r in journal_rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        events.append(
            {
                "type": str(r["kind"] or ""),
                "payload": payload if isinstance(payload, dict) else {},
                "turn_id": str(r["turn_id"] or ""),
                "seq": r["seq"],
            }
        )

    message_costs: dict[str, Any] = {}
    for r in cost_rows:
        message_costs[str(r["id"])] = r["cost"]

    workspace_files: list[str] = []
    root = workspace_root_path(
        user_id=str(conv["user_id"]),
        folder_id=str(conv["folder_id"]) if conv.get("folder_id") else None,
        conversation_id=cid,
    )
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                workspace_files.append(rel)

    return GoldenBundle(
        conversation_id=cid,
        user_prompt=user_prompt,
        events=events,
        workspace_files=workspace_files,
        message_costs=message_costs,
    )


async def _amain(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="批C 黄金场六环离线验收（只读 DB/工作区，不调 LLM）"
    )
    ap.add_argument(
        "conversation_id",
        nargs="?",
        default=None,
        help="conversation UUID（也可用 --trace）",
    )
    ap.add_argument("--trace", default=None, help="32-hex trace_id → 解析 conversation")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    ap.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="离线 JSON fixture（{user_prompt,events,workspace_files,message_costs?}）",
    )
    args = ap.parse_args(argv)

    if args.fixture:
        raw = json.loads(args.fixture.read_text(encoding="utf-8"))
        bundle = GoldenBundle(
            conversation_id=str(raw.get("conversation_id") or args.fixture.stem),
            user_prompt=str(raw.get("user_prompt") or ""),
            events=list(raw.get("events") or []),
            workspace_files=list(raw.get("workspace_files") or []),
            message_costs=dict(raw.get("message_costs") or {}),
            gaps=list(raw.get("gaps") or []),
        )
    else:
        target = args.trace or args.conversation_id
        if not target:
            ap.error("需要 conversation_id 或 --trace 或 --fixture")
        bundle = await load_bundle_from_db(str(target))

    report = evaluate_rings(bundle)
    if args.json:
        print(
            json.dumps(
                {
                    "conversation_id": bundle.conversation_id,
                    "user_prompt": bundle.user_prompt[:200],
                    "event_count": len(bundle.events),
                    "workspace_files": bundle.workspace_files,
                    **report.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_report(report, conversation_id=bundle.conversation_id))
        print(f"\nevents={len(bundle.events)} workspace_files={len(bundle.workspace_files)}")

    return 0 if report.all_pass else 2


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
