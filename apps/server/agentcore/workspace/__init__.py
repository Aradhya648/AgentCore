"""Workspace backends — the file + execution seam for tools.

``WorkspaceBackend`` is the abstraction every filesystem / code-execution tool
talks to. Two implementations plug into the same seam without touching the engine
or tools: ``ServerWorkspace`` (cloud mode, files + execution on the server) and
``LocalWorkspace`` (local mode, every op routed over a ``WorkspaceChannel`` to the
user's desktop). The channel is the generalized form of the approval mechanism.
"""

from agentcore.workspace.channel import WorkspaceChannel, WorkspaceOp
from agentcore.workspace.local import LocalWorkspace
from agentcore.workspace.protocol import (
    AmbiguousMatch,
    DirEntry,
    GrepHit,
    GrepQuery,
    GrepResult,
    NoMatch,
    NotADirectory,
    NotAFile,
    NotUTF8,
    OutsideWorkspace,
    PathNotFound,
    ReplaceOutcome,
    WorkspaceBackend,
    WorkspaceError,
    WorkspaceIOError,
)
from agentcore.workspace.server import ServerWorkspace

__all__ = [
    "WorkspaceBackend",
    "ServerWorkspace",
    "LocalWorkspace",
    "WorkspaceChannel",
    "WorkspaceOp",
    "WorkspaceError",
    "OutsideWorkspace",
    "PathNotFound",
    "NotAFile",
    "NotADirectory",
    "NotUTF8",
    "NoMatch",
    "AmbiguousMatch",
    "WorkspaceIOError",
    "DirEntry",
    "GrepHit",
    "GrepQuery",
    "GrepResult",
    "ReplaceOutcome",
]
