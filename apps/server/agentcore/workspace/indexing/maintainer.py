"""Background code-index maintenance — never on the ``code_search`` critical path."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from agentcore.core.logging import get_logger

if TYPE_CHECKING:
    from agentcore.workspace.indexing.manager import IndexManager
    from agentcore.workspace.protocol import WorkspaceBackend

logger = get_logger(__name__)


class IndexMaintainer:
    """Coalesced background ``ensure_index`` for one workspace backend.

    ``code_search`` only queries; this owner builds/refreshes. Concurrent
    ``schedule`` calls coalesce into one run (+ one follow-up if dirty again).
    """

    def __init__(self, manager: IndexManager, backend: WorkspaceBackend) -> None:
        self._manager = manager
        self._backend = backend
        self._task: asyncio.Task[None] | None = None
        self._force = False
        self._rerun = False
        self._lock = asyncio.Lock()

    @property
    def building(self) -> bool:
        return self._task is not None and not self._task.done()

    def schedule(self, *, force: bool = False) -> None:
        """Fire-and-forget ensure; safe to call from sync mutation paths."""
        if force:
            self._force = True
        if self.building:
            self._rerun = True
            self._manager.set_building(True)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._manager.set_building(True)
        self._task = loop.create_task(self._run(), name="code-index-maintain")

    async def _run(self) -> None:
        async with self._lock:
            try:
                force = self._force
                self._force = False
                await self._manager.ensure_index(self._backend, force=force)
            except Exception:
                logger.exception("workspace.index_failed")
            finally:
                self._manager.set_building(False)
                if self._rerun:
                    self._rerun = False
                    self.schedule()
