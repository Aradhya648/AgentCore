"""Reset memory consolidation watermarks for users with empty memory files.

Use after fixing the extraction prompt so previously "consumed" conversations can
be re-processed by the offline sweeper. Touches users whose global 偏好+画像 are
empty and who hold no topic / project memory notes (memory is product-always-on).

Run from ``apps/server``::

    # preview (default)
    uv run python scripts/backfill_memory.py

    # apply resets
    uv run python scripts/backfill_memory.py --apply
"""

from __future__ import annotations

import argparse
import asyncio

from agentcore.memory.backfill import backfill_empty_memory_watermarks


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset memory_synced_at for users with empty memory."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform resets (default is dry-run preview only).",
    )
    return parser.parse_args()


def _print_stats(*, dry_run: bool, stats) -> None:
    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"\nMemory backfill ({mode})")
    print(f"  users scanned:                  {stats.users_scanned}")
    print(f"  users skipped (has memory):     {stats.users_skipped_has_memory}")
    print(f"  users reset:                    {stats.users_reset}")
    print(f"  conversations reset:            {stats.conversations_reset}")
    if dry_run and stats.conversations_reset:
        print("\nRe-run with --apply to perform the resets.")


async def main() -> None:
    args = _parse_args()
    dry_run = not args.apply
    if dry_run:
        print("Dry run — no database changes. Pass --apply to reset watermarks.")
    stats = await backfill_empty_memory_watermarks(dry_run=dry_run)
    _print_stats(dry_run=dry_run, stats=stats)


if __name__ == "__main__":
    asyncio.run(main())
