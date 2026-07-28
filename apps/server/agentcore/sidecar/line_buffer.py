"""Chunked NDJSON line framing (Desktop-homologous).

Readers of the sidecar stdout channel must **not** use ``readline()``. On Windows
a large framed line (e.g. ``run_context``) can fill the pipe before ``\\n`` arrives:
``readline`` blocks waiting for the rest while the writer blocks on ``write`` →
deadlock. Desktop drains via ``data`` chunks + buffer; this helper is the same
algorithm for Python probes.

Callers must feed chunks from a short-read API (``os.read(fileno)`` / one raw
pipe read), **not** ``TextIOWrapper.read(n)`` — the latter keeps reading until
*n* characters arrive and hangs after a short NDJSON line.
"""

from __future__ import annotations


def append_stdout_chunk(buffer: str, chunk: str) -> tuple[str, list[str]]:
    """Accumulate ``chunk`` into ``buffer``; return ``(remainder, complete_lines)``.

    Complete lines are stripped of the trailing ``\\n`` but otherwise unmodified
    (callers trim / ``json.loads``). Empty/whitespace-only lines are dropped —
    same as Desktop ``sidecar-service.ts``.
    """
    buffer = buffer + chunk
    lines: list[str] = []
    while True:
        idx = buffer.find("\n")
        if idx < 0:
            break
        line = buffer[:idx]
        buffer = buffer[idx + 1 :]
        if line.strip():
            lines.append(line)
    return buffer, lines
