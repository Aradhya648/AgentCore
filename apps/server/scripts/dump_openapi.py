"""Dump the FastAPI OpenAPI spec to ``apps/server/openapi.json``.

This committed spec is the single source of truth for REST TS types
(``packages/contract-rest-types``). Regenerate via ``pnpm gen:types`` at repo root.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from agentcore.main import app


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via temp + ``os.replace`` — avoids Windows ``Errno 22`` on in-place rewrite
    when a prior gen still has the file briefly locked (AV / indexer / handle linger).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def main() -> None:
    spec = app.openapi()
    out = Path(__file__).resolve().parents[1] / "openapi.json"
    _atomic_write_text(
        out,
        json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
    print(f"wrote {out} ({len(spec.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
