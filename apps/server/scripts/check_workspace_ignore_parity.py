#!/usr/bin/env python3
"""CLI for workspace ignore-list parity (Python ↔ desktop TypeScript).

Usage (from apps/server)::

    uv run python scripts/check_workspace_ignore_parity.py
    uv run python scripts/check_workspace_ignore_parity.py --simulate-drift

Wired into ``pnpm release:gate`` (backend section) and unit pytest.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Workspace ignore-list parity: _paths.py ↔ workspaceIgnore.ts"
    )
    parser.add_argument(
        "--simulate-drift",
        action="store_true",
        help="Self-test: inject a phantom TS member and expect failure",
    )
    args = parser.parse_args(argv)

    from agentcore.workspace.ignore_parity import run_ignore_parity

    result = run_ignore_parity(simulate_drift=args.simulate_drift)
    print(f"python: {result.py_path}")
    print(f"typescript: {result.ts_path}")

    if result.ok:
        if args.simulate_drift:
            print("✗ ignore parity unexpectedly passed under --simulate-drift")
            return 1
        print("✓ workspace ignore lists aligned (dirs / system / ai-noise)")
        return 0

    print("✗ workspace ignore parity FAILED — Python ↔ TypeScript diverge:")
    for err in result.errors:
        print(f"  - {err}")
    if args.simulate_drift:
        print("✓ simulate-drift intercepted mismatch as expected")
        return 0
    print(
        "  Fix: edit both apps/server/agentcore/workspace/_paths.py and "
        "apps/desktop/src/main/fs/workspaceIgnore.ts, then re-run."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
