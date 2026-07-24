"""CLI: ``python -m agentcore.simulation.show produce --episode 3``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentcore.simulation.show.produce import FIXED_EP3_SEED, produce_episode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线生产恋综一期 run + EpisodeManifest")
    parser.add_argument("command", choices=["produce"], help="produce = 录播生产")
    parser.add_argument("--episode", type=int, default=3)
    parser.add_argument("--seed", type=int, default=FIXED_EP3_SEED)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="输出目录（默认 apps/server/eval-out/show-episode-N）",
    )
    parser.add_argument("--run-id", type=str, default=None)
    args = parser.parse_args(argv)

    if args.command != "produce":
        parser.error(f"unknown command {args.command}")

    produced = produce_episode(
        episode_no=args.episode,
        seed=args.seed,
        run_id=args.run_id,
    )
    out = args.out
    if out is None:
        # apps/server/eval-out/...
        out = Path(__file__).resolve().parents[3] / "eval-out" / f"show-episode-{args.episode}"
    produced.write(out)
    summary = {
        "run_id": produced.run_id,
        "seed": produced.seed,
        "episode_no": produced.episode_no,
        "out": str(out.resolve()),
        "manifest_title": produced.manifest.get("title"),
        "events": len(produced.events),
        "segments": len(produced.manifest.get("segments") or []),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
