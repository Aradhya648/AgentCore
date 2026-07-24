"""Workspace file I/O service — bring user files in and take results out.

The HTTP file-in/out counterpart to the agent's file tools (文件进出·先上传).
It resolves a conversation to its workspace backend (cloud mode today, local
mode later — same seam) and goes through ``WorkspaceBackend`` so upload/download
respect the traversal guard and will route to the desktop unchanged under
``LocalWorkspace``. Path policy lives in ``locate``; this layer never touches a
raw ``Path``.
"""

from __future__ import annotations

from typing import Literal

from agentcore.workspace.locate import build_server_workspace
from agentcore.workspace.protocol import DirEntry


async def list_files(
    *, user_id: str, folder_id: str | None, conversation_id: str, recursive: bool = False
) -> list[DirEntry]:
    """List entries in the conversation's workspace (top level or recursive)."""
    backend = build_server_workspace(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    pattern = "**/*" if recursive else "*"
    return await backend.list(".", pattern)


async def list_file_index(
    *, user_id: str, folder_id: str | None, conversation_id: str
) -> tuple[list[str], bool]:
    """Flat, ignore-pruned, capped file-path list for @ mentions (文件中枢统一 F4).

    Returns ``(paths, truncated)``. Cloud-only by construction — the route gates
    local workspaces with 409 (their files live on the desktop and are indexed
    there). Mirrors the desktop ``fsApi.listFiles`` so @ behaves the same across
    cloud and local.
    """
    backend = build_server_workspace(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return await backend.index_files()


async def upload_file(
    *, user_id: str, folder_id: str | None, conversation_id: str, path: str, data: bytes
) -> int:
    """Write ``data`` to ``path`` in the conversation's workspace; return bytes."""
    backend = build_server_workspace(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return await backend.write_bytes(path, data)


async def download_file(
    *, user_id: str, folder_id: str | None, conversation_id: str, path: str
) -> bytes:
    """Return the raw bytes of ``path`` in the conversation's workspace."""
    backend = build_server_workspace(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return await backend.read_bytes(path)


async def create_dir(
    *, user_id: str, folder_id: str | None, conversation_id: str, path: str
) -> None:
    """Create directory ``path`` (with parents) in the conversation's workspace."""
    backend = build_server_workspace(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    await backend.mkdir(path)


async def delete_file(
    *, user_id: str, folder_id: str | None, conversation_id: str, path: str
) -> None:
    """Delete ``path`` (file or directory) in the conversation's workspace."""
    backend = build_server_workspace(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    await backend.delete(path)


async def move_file(
    *, user_id: str, folder_id: str | None, conversation_id: str, src: str, dst: str
) -> None:
    """Move/rename ``src`` to ``dst`` in the conversation's workspace."""
    backend = build_server_workspace(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    await backend.move(src, dst)


async def read_file_for_edit(
    *, user_id: str, folder_id: str | None, conversation_id: str, path: str
) -> tuple[str, int, Literal["lf", "crlf"]]:
    """Read ``path`` for editing: ``(text, mtime_ms, eol)`` — full text + CAS baseline.

    Unlike :func:`download_file` (raw bytes, used for truncated preview), this reads
    the whole text and reports the mtime baseline so an in-panel save can do a
    write-time CAS instead of blind-clobbering a file an Agent turn changed.
    """
    backend = build_server_workspace(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return await backend.read_for_edit(path)


async def write_file_text(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    path: str,
    content: str,
    baseline_mtime_ms: int,
    eol: Literal["lf", "crlf"],
) -> tuple[bool, int]:
    """Conditionally write editor text to ``path``; ``(ok, mtime_ms)`` (mtime CAS).

    ``ok`` False means a conflict (disk changed since ``baseline_mtime_ms``) and the
    returned mtime is the current disk version. Callers must hold ``workspace_lock``
    so the CAS is atomic against a same-workspace Agent turn.
    """
    backend = build_server_workspace(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return await backend.write_text_cas(path, content, baseline_mtime_ms=baseline_mtime_ms, eol=eol)
