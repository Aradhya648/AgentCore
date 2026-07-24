#!/usr/bin/env python3
"""CLI for the migration↔ORM schema gate.

Usage (from apps/server)::

    uv run python scripts/check_schema_gate.py
    uv run python scripts/check_schema_gate.py --live          # needs DB at head
    uv run python scripts/check_schema_gate.py --simulate-stale-orm  # expect fail

Wired into ``pnpm release:gate`` (offline) and ``finish-server.sh`` (live after
migrate, before traffic cutover).
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migration head ↔ ORM schema gate")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also run alembic check against DATABASE_URL (DB must already be at head)",
    )
    parser.add_argument(
        "--simulate-stale-orm",
        action="store_true",
        help="Self-test: inject a known tombstone mismatch and expect failure",
    )
    args = parser.parse_args(argv)

    from agentcore.db.schema_gate import run_schema_gate

    result = run_schema_gate(
        live=args.live,
        simulate_stale_orm=args.simulate_stale_orm,
    )

    print(f"alembic heads: {', '.join(result.heads) or '(none)'}")
    if result.dropped_tables:
        print(f"net dropped tables: {', '.join(result.dropped_tables)}")
    if result.dropped_columns:
        cols = ", ".join(f"{t}.{c}" for t, c in result.dropped_columns)
        print(f"net dropped columns: {cols}")

    for warning in result.warnings:
        print(f"WARN: {warning}")

    if result.ok:
        if args.simulate_stale_orm:
            print("✗ schema gate unexpectedly passed under --simulate-stale-orm")
            return 1
        mode = "live" if args.live else "offline"
        print(f"✓ schema gate passed ({mode})")
        return 0

    print("✗ schema gate FAILED — migration head / ORM metadata diverge:")
    for err in result.errors:
        print(f"  - {err}")
    if args.simulate_stale_orm:
        print("✓ simulate-stale-orm intercepted mismatch as expected")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
