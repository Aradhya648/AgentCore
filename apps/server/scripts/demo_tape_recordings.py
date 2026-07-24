"""List / search demo-tape live-stream recordings (``demos/recordings/``).

From apps/server::

    uv run python scripts/demo_tape_recordings.py
    uv run python scripts/demo_tape_recordings.py --query 茉莉
    uv run python scripts/demo_tape_recordings.py --dir ../../demos/recordings \\
        --query c63a1188

Filenames are ``<message_id>.json``; this CLI prints conversation_id / recorded_at /
event counts / a short content snippet so you can find the right take before export.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentcore.demo_tape.recordings_index import (
    format_recording_table,
    list_recordings,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dir",
        default=None,
        help="Recordings directory (default: demos/recordings or DEMO_TAPE_RECORDINGS_DIR)",
    )
    p.add_argument(
        "--query",
        "-q",
        default="",
        help="Substring filter on message_id / conversation_id / recorded_at / snippet",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max rows (0 = all)",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    directory = Path(args.dir) if args.dir else None
    rows = list_recordings(directory=directory, query=args.query)
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    root = directory if directory is not None else None
    if root is None:
        from agentcore.demo_tape.recorder import recordings_dir

        root = recordings_dir()
    print(f"recordings dir: {root}  ({len(rows)} match)")
    print(format_recording_table(rows))


if __name__ == "__main__":
    main()
