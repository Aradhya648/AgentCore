#!/usr/bin/env python3
"""R1a 兼容入口 → ``r1_control.py --suite r1a``.

保留旧命令以免文档/肌肉记忆断裂::

    python evals/code-capability/r1a_control.py --mode matrix
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from r1_control import main  # noqa: E402


def _inject_suite(argv: list[str]) -> list[str]:
    if "--suite" in argv:
        return argv
    return ["--suite", "r1a", *argv]


if __name__ == "__main__":
    raise SystemExit(main(_inject_suite(sys.argv[1:])))
