"""Export a live-stream recording into demos/tapes/*.json.

The journal-reconstruction exporter is retired — tapes are cut from recordings.
Record the run first (``DEMO_TAPE_RECORD_ENABLED=true`` in apps/server/.env →
``demos/recordings/<message_id>.json``), then, from apps/server::

    # Single act (unchanged)
    uv run python scripts/demo_tape_export.py \\
        --message-id <assistant message id> \\
        --title "我的演示" \\
        --out ../../demos/tapes/my-demo.json

    # Multi-act script: repeat --message-id (or --recording) in play order
    uv run python scripts/demo_tape_export.py \\
        --message-id <act1-msg-id> \\
        --message-id <act2-msg-id> \\
        --title "多幕演示" \\
        --out ../../demos/tapes/my-multi.json

``--user-prompt`` overrides the DB lookup of the triggering user message (needed
when exporting on a box without the source conversation). For multi-act exports
it applies only when a single act is being cut with one shared override is not
enough — prefer per-recording DB lookup, or pass one prompt only for single-act.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from agentcore.db.base import async_session_factory
from agentcore.demo_tape.export import (
    TapeExportRefusedError,
    assemble_multi_turn_tape,
    build_tape_from_recording,
    write_tape,
)
from agentcore.demo_tape.recorder import load_recording, recording_path
from agentcore.demo_tape.sanitize import IngestScanError


async def _lookup_user_prompt(conversation_id: str, message_id: str) -> str:
    """The user message that triggered the recorded turn (best-effort)."""
    try:
        async with async_session_factory() as s:
            row = (
                await s.execute(
                    text(
                        """
                        SELECT content FROM messages
                        WHERE conversation_id = :cid AND role = 'user'
                          AND created_at <= coalesce(
                            (SELECT created_at FROM messages WHERE id = :mid), now()
                          )
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"cid": conversation_id, "mid": message_id},
                )
            ).mappings().first()
        return str(row["content"]) if row and row["content"] else ""
    except Exception as e:  # noqa: BLE001 — DB is optional here; --user-prompt covers it
        print(f"warn: user-prompt DB lookup failed ({e}); pass --user-prompt")
        return ""


async def _cut_one(
    *,
    rec_path: Path,
    message_id_hint: str,
    title: str,
    user_prompt_override: str,
    followups: list[str] | None,
    force: bool,
) -> dict:
    print(f"demo_tape.export_start recording={rec_path}")
    recording = load_recording(rec_path)
    rec_meta = recording.get("meta") or {}
    conversation_id = str(rec_meta.get("conversation_id") or "")
    message_id = str(rec_meta.get("message_id") or message_id_hint or "")
    segs = len(recording.get("segments") or [])
    print(
        f"demo_tape.export_meta conversation_id={conversation_id or '-'} "
        f"message_id={message_id or '-'} segments={segs} "
        f"recorded_at={rec_meta.get('recorded_at') or '-'}"
    )

    user_prompt = user_prompt_override or ""
    if not user_prompt and conversation_id:
        user_prompt = await _lookup_user_prompt(conversation_id, message_id)
    if not user_prompt:
        raise SystemExit(
            f"no user prompt for {rec_path} (DB lookup empty) — pass --user-prompt"
        )

    tape_meta: dict = {"title": title or Path(rec_path).stem}
    if followups:
        tape_meta["followups"] = list(followups)
    try:
        return build_tape_from_recording(
            recording,
            meta=tape_meta,
            user_prompt=user_prompt,
            force=force,
        )
    except (TapeExportRefusedError, IngestScanError) as e:
        raise SystemExit(f"demo_tape.export_refused: {e}") from e


async def _main(args: argparse.Namespace) -> None:
    message_ids: list[str] = list(args.message_id or [])
    recordings: list[str] = list(args.recording or [])
    if message_ids and recordings:
        raise SystemExit("use either repeated --message-id or repeated --recording, not both")
    if not message_ids and not recordings:
        raise SystemExit("provide --message-id or --recording (repeat for multi-act)")

    sources: list[tuple[str, str]] = (
        [("id", mid) for mid in message_ids]
        if message_ids
        else [("path", p) for p in recordings]
    )

    title = args.title or Path(args.out).stem
    turn_docs: list[dict] = []
    for kind, spec in sources:
        if kind == "id":
            rec_path = recording_path(spec)
            mid_hint = spec
        else:
            rec_path = Path(spec)
            mid_hint = ""
        if not rec_path.exists():
            raise SystemExit(
                f"recording not found: {rec_path}\n"
                "Record the run first: set DEMO_TAPE_RECORD_ENABLED=true, restart the "
                "backend, run the turn, then re-export.\n"
                "List takes: uv run python scripts/demo_tape_recordings.py"
            )
        # Single-act: --user-prompt / --followups apply. Multi-act: only title is
        # shared; each act keeps its own prompt/followups from recording/DB.
        prompt_override = args.user_prompt if len(sources) == 1 else ""
        followups = args.followups if len(sources) == 1 else None
        doc = await _cut_one(
            rec_path=rec_path,
            message_id_hint=mid_hint,
            title=title,
            user_prompt_override=prompt_override,
            followups=followups,
            force=bool(args.force),
        )
        turn_docs.append(doc)

    if len(turn_docs) == 1:
        doc = turn_docs[0]
    else:
        doc = assemble_multi_turn_tape(turn_docs, meta={"title": title})

    out = Path(args.out)
    write_tape(out, doc)
    if "turns" in doc and len(doc["turns"]) > 1:
        print(
            f"demo_tape.export_done wrote={out} turns={len(doc['turns'])} "
            f"events={doc['meta']['event_count']} "
            f"duration_ms={doc['meta']['duration_ms']}"
        )
    else:
        chips = doc["meta"].get("followups") or []
        print(
            f"demo_tape.export_done wrote={out} events={doc['meta']['event_count']} "
            f"duration_ms={doc['meta']['duration_ms']} "
            f"followups={len(chips)}"
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--message-id",
        action="append",
        default=[],
        help="Assistant message id (repeat in play order for multi-act)",
    )
    p.add_argument(
        "--recording",
        action="append",
        default=[],
        help="Explicit recording file path (repeat in play order; overrides id lookup)",
    )
    p.add_argument("--title", default="", help="Tape title (command palette entry)")
    p.add_argument(
        "--user-prompt",
        default="",
        help="Override the DB user-prompt lookup (single-act only)",
    )
    p.add_argument(
        "--followups",
        nargs="+",
        default=None,
        help=(
            "Override meta.followups for a single-act export "
            "(otherwise lifted from recorded followups_generated)"
        ),
    )
    p.add_argument("--out", required=True, help="Output tape path (relative to cwd)")
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "Override export refusal for unwired pause kinds (none among cold-path "
            "today) and approval_* events. Does not bypass client-tool assertion "
            "or ingest memory/PII scan."
        ),
    )
    args = p.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
