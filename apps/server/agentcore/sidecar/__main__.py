"""Sidecar entrypoint: ``python -m agentcore.sidecar``.

Runs the stdio JSON-RPC loop that the desktop drives. Two transport invariants
matter here and are set up before anything else:

1. **stdout is the JSON-RPC channel — nothing else may write to it.** Logging
   (and any stray ``print``) is redirected to stderr by pointing ``sys.stdout`` at
   ``sys.stderr`` *before* ``setup_logging`` runs (it binds its handler to the
   then-current ``sys.stdout``). The framed writer keeps a private handle to the
   real stdout.
2. **UTF-8 both ways.** Windows consoles default to a legacy code page; the streams
   are reconfigured to UTF-8 so non-ASCII content round-trips.

Both stdin reads and stdout write+flush run on a worker thread
(``asyncio.to_thread``) so a blocked pipe never freezes the event loop —
``respond`` / ``cancel`` stay serviceable while a turn streams. (A sync
write/flush on a full Windows pipe would otherwise stall the loop mid-turn.)
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import TextIO

from agentcore.core.logging import get_logger, setup_logging
from agentcore.sidecar.server import SidecarServer


def _claim_stdout() -> TextIO:
    """Take ownership of the real stdout for framing; send everything else to stderr.

    Returns the private stdout handle. Must run before ``setup_logging`` so the log
    handler binds to stderr, not the JSON-RPC channel.
    """
    real_stdout = sys.stdout
    # ``reconfigure`` exists on the standard TextIOWrapper streams; guard anyway so
    # an exotic wrapped stream (e.g. under a test runner) cannot abort startup.
    with contextlib.suppress(Exception):
        real_stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    with contextlib.suppress(Exception):
        sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    # Anything that writes to ``sys.stdout`` from now on (logs, prints) goes to
    # stderr and can never corrupt the framed channel.
    sys.stdout = sys.stderr
    return real_stdout


async def _serve(real_stdout: TextIO) -> None:
    logger = get_logger(__name__)
    write_lock = asyncio.Lock()

    async def write_line(line: str) -> None:
        # One writer at a time: turn-event notifications and method responses are
        # produced by concurrent tasks, and an interleaved write would corrupt a
        # frame. write+flush goes to a worker thread (stdin already does) so a
        # blocked pipe cannot freeze the event loop.
        async with write_lock:

            def _write_and_flush() -> None:
                real_stdout.write(line)
                real_stdout.flush()

            await asyncio.to_thread(_write_and_flush)

    server = SidecarServer(write_line)
    logger.info("sidecar.ready")

    while not server.shutdown_requested.is_set():
        line = await asyncio.to_thread(sys.stdin.readline)
        if line == "":  # EOF — the desktop closed the pipe
            logger.info("sidecar.stdin_closed")
            break
        await server.handle_line(line)
    logger.info("sidecar.exiting")


def main() -> None:
    real_stdout = _claim_stdout()
    setup_logging()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve(real_stdout))


if __name__ == "__main__":
    main()
