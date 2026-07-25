"""Workspace as a first-class, addressable resource (文件中枢统一 Step 1).

文件夹即工作区: a workspace **is** a folder, addressed by its own id
(``folder:<id>``, see ``workspace.locate``) rather than only "through a
conversation". This router is that surface: enumerate a user's workspaces, then
read/CRUD/snapshot any one by id.

Addressing is the only thing new here — the actual file/snapshot/clone logic stays
single-sourced in the ``workspace.*`` service layer that the per-conversation
routes also call (those remain the thin per-conversation alias). Every route is
owner-scoped: the ``ident`` in a ws id is resolved against the user's own folders,
so a non-owner (or a bad id) gets 404 — never another user's data.

Cloud vs local (§五 边界): a **local** workspace's files live on the user's
machine and are reached over desktop IPC, not here; its server-side dir is not the
truth. So file/dir/move/clone and snapshot create/restore reject local ids with
409 — the hub routes those to the desktop. Read-only snapshot list/download stay
open (snapshots are object-store backed, keyed by ws, even for local).
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from agentcore.api.dependencies import (
    AuthUser,
    get_conversation_repo,
    get_folder_repo,
    get_shared_space_service,
)
from agentcore.api.download_headers import download_headers
from agentcore.api.schemas import (
    CloneRepoRequest,
    CloneRepoResponse,
    ConvertMdToDocxRequest,
    ConvertMdToDocxResponse,
    CreateDirRequest,
    CreateSnapshotRequest,
    ExportDocxRequest,
    ExportDocxResponse,
    MoveFileRequest,
    SnapshotListResponse,
    SnapshotSummary,
    StatusResponse,
    UploadFileResponse,
    WorkspaceEditDoc,
    WorkspaceFileEntry,
    WorkspaceFileIndexResponse,
    WorkspaceFileListResponse,
    WorkspaceListResponse,
    WorkspaceSummary,
    WorkspaceWriteRequest,
    WorkspaceWriteResult,
)
from agentcore.config import settings
from agentcore.conversation.scratch import bare_chat_local_subpath
from agentcore.core.errors import ConflictError, NotFoundError, ValidationError
from agentcore.db.repositories import ConversationRepository, FolderRepository
from agentcore.docs_export.md_to_docx import (
    convert_markdown_to_docx,
    docx_path_for_markdown,
)
from agentcore.docs_export.workspace_export import ExportMarkdownError, export_markdown_path
from agentcore.shared_spaces.service import SharedSpaceService
from agentcore.shared_spaces.types import can_write
from agentcore.storage import SnapshotNotFound
from agentcore.workspace.files import (
    create_dir,
    delete_file,
    download_file,
    list_file_index,
    list_files,
    move_file,
    read_file_for_edit,
    upload_file,
    write_file_text,
)
from agentcore.workspace.git import CloneError, clone_repo
from agentcore.workspace.locate import (
    build_server_workspace,
    build_shared_workspace,
    format_shared_workspace_id,
    parse_workspace_id,
    workspace_has_entries,
    workspace_storage_key,
)
from agentcore.workspace.locks import workspace_lock
from agentcore.workspace.protocol import (
    AlreadyExists,
    NotAFile,
    NotUTF8,
    OutsideWorkspace,
    PathNotFound,
)
from agentcore.workspace.shared_paths import (
    shared_workspace_has_entries,
    shared_workspace_storage_key,
)
from agentcore.workspace.snapshots import (
    create_snapshot,
    list_snapshots,
    read_snapshot,
    restore_snapshot,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@dataclass(frozen=True)
class _WsTarget:
    """A resolved workspace — folder/conv (owner-scope) or shared space (membership)."""

    ws_id: str
    folder_id: str | None
    conversation_id: str  # "" for a folder workspace (its path ignores it)
    name: str
    location: Literal["cloud", "local"]
    root_id: str | None
    space_id: str | None = None
    member_role: str | None = None


async def _resolve_owned_workspace(
    ws_id: str,
    user_id: str,
    conv_repo: ConversationRepository,
    folder_repo: FolderRepository,
    shared_svc: SharedSpaceService | None = None,
) -> _WsTarget:
    """Resolve a ws id to an owned project/scratch or a shared space, or 404.

    Owner-scope folder/conv resolution is unchanged. ``shared:`` is an additive
    membership branch (independent of owner-scope repos).
    """
    try:
        parsed = parse_workspace_id(ws_id)
    except ValueError as e:
        raise NotFoundError("工作区不存在") from e

    if parsed.kind == "shared":
        if shared_svc is None:
            raise NotFoundError("工作区不存在")
        space, member = await shared_svc.require_member_for_ws(
            space_id=parsed.ident, user_id=user_id
        )
        return _WsTarget(
            ws_id=ws_id,
            folder_id=None,
            conversation_id="",
            name=space.name,
            location="cloud",
            root_id=None,
            space_id=space.id,
            member_role=member.role,
        )

    if parsed.kind == "conv":
        conv = await conv_repo.get_by_id(parsed.ident, user_id=user_id)
        if not conv:
            raise NotFoundError("工作区不存在")
        # Project chats address via folder:<id>; a bare conv: id that somehow
        # carries folder_id still resolves to the conversation row for alias paths.
        if conv.folder_id:
            folder = await folder_repo.get_by_id(conv.folder_id, user_id=user_id)
            if not folder:
                raise NotFoundError("工作区不存在")
            return _WsTarget(
                ws_id=f"folder:{folder.id}",
                folder_id=folder.id,
                conversation_id=conv.id,
                name=folder.name,
                location="local" if folder.local_root_id else "cloud",
                root_id=folder.local_root_id,
            )
        return _WsTarget(
            ws_id=ws_id,
            folder_id=None,
            conversation_id=conv.id,
            name=conv.title or "未命名对话",
            location="local" if conv.local_root_id else "cloud",
            root_id=conv.local_root_id,
        )

    folder = await folder_repo.get_by_id(parsed.ident, user_id=user_id)
    if not folder:
        raise NotFoundError("工作区不存在")
    return _WsTarget(
        ws_id=ws_id,
        folder_id=folder.id,
        conversation_id="",
        name=folder.name,
        location="local" if folder.local_root_id else "cloud",
        root_id=folder.local_root_id,
    )


def _require_cloud(target: _WsTarget) -> None:
    """Reject ops that only make sense server-side on a local workspace (§五).

    A local workspace's files live on the user's machine; the hub reaches them
    over desktop IPC, so writing/snapshotting the server-side mirror here would
    silently diverge from the truth.
    """
    if target.location == "local":
        raise ConflictError("本地工作区的文件请在桌面端访问")


def _require_shared_write(target: _WsTarget) -> None:
    if target.space_id and not can_write(target.member_role or "viewer"):  # type: ignore[arg-type]
        raise ConflictError("只读成员不能写入共享空间")


def _refuse_shared_extra(target: _WsTarget) -> None:
    """v1: shared spaces support file CRUD only (no clone / snapshot)."""
    if target.space_id:
        raise ConflictError("共享空间暂不支持此操作")


def _storage_key(user_id: str, target: _WsTarget) -> str:
    if target.space_id:
        return shared_workspace_storage_key(target.space_id)
    return workspace_storage_key(
        user_id=user_id,
        folder_id=target.folder_id,
        conversation_id=target.conversation_id,
    )


async def _list_shared_entries(space_id: str, *, recursive: bool) -> list:
    backend = build_shared_workspace(space_id)
    pattern = "**/*" if recursive else "*"
    return await backend.list(".", pattern)


async def _shared_upload(space_id: str, path: str, data: bytes) -> int:
    backend = build_shared_workspace(space_id)
    return await backend.write_bytes(path, data)


async def _shared_download(space_id: str, path: str) -> bytes:
    backend = build_shared_workspace(space_id)
    return await backend.read_bytes(path)


async def _shared_read_edit(space_id: str, path: str):
    backend = build_shared_workspace(space_id)
    return await backend.read_for_edit(path)


async def _shared_write_cas(
    space_id: str,
    path: str,
    content: str,
    *,
    baseline_mtime_ms: int,
    eol: Literal["lf", "crlf"],
):
    backend = build_shared_workspace(space_id)
    return await backend.write_text_cas(
        path, content, baseline_mtime_ms=baseline_mtime_ms, eol=eol
    )


async def _shared_mkdir(space_id: str, path: str) -> None:
    backend = build_shared_workspace(space_id)
    await backend.mkdir(path)


async def _shared_delete(space_id: str, path: str) -> None:
    backend = build_shared_workspace(space_id)
    await backend.delete(path)


async def _shared_move(space_id: str, src: str, dst: str) -> None:
    backend = build_shared_workspace(space_id)
    await backend.move(src, dst)


async def _shared_index(space_id: str) -> tuple[list[str], bool]:
    backend = build_shared_workspace(space_id)
    return await backend.index_files()


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Enumerate project workspaces + bare-chat scratches + shared spaces."""
    folders = await folder_repo.list_by_user(user.user_id)
    items: list[WorkspaceSummary] = []
    for folder in folders:
        local = folder.local_root_id is not None
        has_files = (
            True
            if local
            else workspace_has_entries(
                user_id=user.user_id, folder_id=folder.id, conversation_id=""
            )
        )
        # Projects always list (a project is a project), even when empty cloud.
        items.append(
            WorkspaceSummary(
                ws_id=f"folder:{folder.id}",
                name=folder.name,
                location="local" if local else "cloud",
                root_id=folder.local_root_id,
                subpath=folder.local_subpath,
                has_files=has_files if not local else True,
            )
        )

    conversations = await conv_repo.list_all_by_user(user.user_id)
    for conv in conversations:
        if conv.folder_id is not None:
            continue  # covered by project entry above
        root_id = conv.local_root_id or conv.local_container_root_id
        local = root_id is not None
        has_files = (
            True
            if local
            else workspace_has_entries(
                user_id=user.user_id, folder_id=None, conversation_id=conv.id
            )
        )
        if not local and not has_files:
            continue
        items.append(
            WorkspaceSummary(
                ws_id=f"conv:{conv.id}",
                name=conv.title or "未命名对话",
                location="local" if local else "cloud",
                root_id=root_id,
                subpath=(
                    (conv.local_subpath or bare_chat_local_subpath(conv.id)) if local else None
                ),
                has_files=has_files,
            )
        )

    for space_view in await shared_svc.list_spaces(user_id=user.user_id):
        items.append(
            WorkspaceSummary(
                ws_id=format_shared_workspace_id(space_view.id),
                name=space_view.name,
                location="cloud",
                root_id=None,
                subpath=None,
                has_files=shared_workspace_has_entries(space_view.id),
            )
        )
    return WorkspaceListResponse(data=items, total=len(items))


# --- Workspace files (cloud workspaces; local ones are reached over IPC) ---


@router.get("/{ws_id}/files", response_model=WorkspaceFileListResponse)
async def list_workspace_files(
    ws_id: str,
    user: AuthUser,
    recursive: bool = Query(False),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """List files in a cloud workspace (top level or recursive)."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    if target.space_id:
        entries = await _list_shared_entries(target.space_id, recursive=recursive)
    else:
        entries = await list_files(
            user_id=user.user_id,
            folder_id=target.folder_id,
            conversation_id=target.conversation_id,
            recursive=recursive,
        )
    return WorkspaceFileListResponse(
        data=[WorkspaceFileEntry.model_validate(e) for e in entries],
        total=len(entries),
    )


@router.get("/{ws_id}/file-index", response_model=WorkspaceFileIndexResponse)
async def list_workspace_file_index(
    ws_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Flat file-path list for @ mentions over a cloud workspace (文件中枢统一 F4).

    Files only, ignore-pruned, capped — so cloud workspace files feed the same @
    index local roots already do. Local workspaces are reached over desktop IPC
    (their files aren't here), so they are refused with 409 like other file ops.
    """
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    if target.space_id:
        paths, truncated = await _shared_index(target.space_id)
    else:
        paths, truncated = await list_file_index(
            user_id=user.user_id,
            folder_id=target.folder_id,
            conversation_id=target.conversation_id,
        )
    return WorkspaceFileIndexResponse(data=paths, total=len(paths), truncated=truncated)


@router.put("/{ws_id}/files/{path:path}", response_model=UploadFileResponse)
async def upload_workspace_file(
    ws_id: str,
    path: str,
    request: Request,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Upload (create/overwrite) a workspace file from the raw request body.

    Body is the file bytes (no multipart); ``path`` is the workspace-relative
    target. Bounded by ``workspace_upload_max_bytes``; a path escaping the
    workspace is rejected (422).
    """
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    _require_shared_write(target)

    max_bytes = settings.workspace_upload_max_bytes
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise ValidationError(f"文件超出 {max_bytes} 字节的上传上限")
    data = await request.body()
    if len(data) > max_bytes:
        raise ValidationError(f"文件超出 {max_bytes} 字节的上传上限")

    if target.space_id:
        shared_svc.check_capacity(target.space_id, incoming_bytes=len(data))

    try:
        async with workspace_lock(_storage_key(user.user_id, target)):
            if target.space_id:
                written = await _shared_upload(target.space_id, path, data)
                await shared_svc.record_file_change(
                    space_id=target.space_id,
                    actor_user_id=user.user_id,
                    actor_via="user",
                    action="file_written",
                    path=path,
                )
            else:
                written = await upload_file(
                    user_id=user.user_id,
                    folder_id=target.folder_id,
                    conversation_id=target.conversation_id,
                    path=path,
                    data=data,
                )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    return UploadFileResponse(path=path, size_bytes=written)


@router.post("/convert/md-to-docx", response_model=ConvertMdToDocxResponse)
async def convert_md_to_docx(
    body: ConvertMdToDocxRequest,
    user: AuthUser,
):
    """Stateless Markdown → Word (shared converter; used by local desktop「导出 Word」).

    Does not touch a workspace. Images are optional base64 payloads keyed by the
    raw Markdown ``src``. Auth required so the surface is not a public converter.
    """
    del user  # auth gate only
    import base64

    images: dict[str, bytes | None] = {}
    for src, b64 in (body.images or {}).items():
        if b64 is None or b64 == "":
            images[src] = None
            continue
        try:
            images[src] = base64.b64decode(b64, validate=False)
        except Exception as e:
            raise ValidationError(f"图片 base64 无效：{src}") from e

    result = convert_markdown_to_docx(body.markdown, images=images)
    suggested = docx_path_for_markdown(body.source_name or "document.md")
    suggested = suggested.rsplit("/", 1)[-1] or "document.docx"
    return ConvertMdToDocxResponse(
        docx_base64=base64.b64encode(result.docx_bytes).decode("ascii"),
        warnings=list(result.warnings),
        suggested_filename=suggested,
    )


@router.post("/{ws_id}/export-docx", response_model=ExportDocxResponse)
async def export_workspace_docx(
    ws_id: str,
    body: ExportDocxRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Export workspace Markdown to a sibling ``.docx`` (shared ``md_to_docx`` converter)."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    _require_shared_write(target)

    try:
        async with workspace_lock(_storage_key(user.user_id, target)):
            if target.space_id:
                backend = build_shared_workspace(target.space_id)
            else:
                backend = build_server_workspace(
                    user_id=user.user_id,
                    folder_id=target.folder_id,
                    conversation_id=target.conversation_id,
                )
            result = await export_markdown_path(backend, body.path)
            if target.space_id:
                await shared_svc.record_file_change(
                    space_id=target.space_id,
                    actor_user_id=user.user_id,
                    actor_via="user",
                    action="file_written",
                    path=result.output_path,
                )
    except ExportMarkdownError as e:
        raise ValidationError(e.message) from e

    return ExportDocxResponse(
        path=result.output_path,
        source_path=result.source_path,
        size_bytes=result.size_bytes,
        warnings=list(result.warnings),
    )


@router.get("/{ws_id}/edit/{path:path}", response_model=WorkspaceEditDoc)
async def read_workspace_file_for_edit(
    ws_id: str,
    path: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Read a cloud workspace file for in-panel editing (full text + mtime baseline).

    The editable counterpart of the truncated preview download — a save needs the
    whole file. Local ids are reached over desktop IPC, so they 409 like other ops.
    """
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    try:
        if target.space_id:
            text, mtime_ms, eol = await _shared_read_edit(target.space_id, path)
        else:
            text, mtime_ms, eol = await read_file_for_edit(
                user_id=user.user_id,
                folder_id=target.folder_id,
                conversation_id=target.conversation_id,
                path=path,
            )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    except (PathNotFound, NotAFile) as e:
        raise NotFoundError("文件不存在") from e
    except NotUTF8 as e:
        raise ValidationError("文件不是 UTF-8 文本，无法编辑") from e
    return WorkspaceEditDoc(text=text, mtime_ms=mtime_ms, eol=eol)


@router.put("/{ws_id}/edit/{path:path}", response_model=WorkspaceWriteResult)
async def write_workspace_file_text(
    ws_id: str,
    path: str,
    body: WorkspaceWriteRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Conditionally write editor text back to a cloud workspace file (mtime CAS).

    ``baseline_mtime_ms`` makes a save that raced an Agent turn return ``conflict``
    instead of clobbering it (云端硬化 §九). Local ids 409 (desktop owns the bytes).
    """
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    _require_shared_write(target)

    max_bytes = settings.workspace_upload_max_bytes
    encoded = body.content.encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValidationError(f"文件超出 {max_bytes} 字节的上传上限")
    if target.space_id:
        shared_svc.check_capacity(target.space_id, incoming_bytes=len(encoded))

    try:
        # CAS + lock: atomic against a running same-space Agent turn.
        async with workspace_lock(_storage_key(user.user_id, target)):
            if target.space_id:
                ok, mtime_ms = await _shared_write_cas(
                    target.space_id,
                    path,
                    body.content,
                    baseline_mtime_ms=body.baseline_mtime_ms,
                    eol=body.eol,
                )
                if ok:
                    await shared_svc.record_file_change(
                        space_id=target.space_id,
                        actor_user_id=user.user_id,
                        actor_via="user",
                        action="file_written",
                        path=path,
                    )
            else:
                ok, mtime_ms = await write_file_text(
                    user_id=user.user_id,
                    folder_id=target.folder_id,
                    conversation_id=target.conversation_id,
                    path=path,
                    content=body.content,
                    baseline_mtime_ms=body.baseline_mtime_ms,
                    eol=body.eol,
                )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    except NotAFile as e:
        raise ValidationError("目标是目录，无法作为文件写入") from e
    return WorkspaceWriteResult(ok=ok, mtime_ms=mtime_ms, conflict=not ok)


@router.get("/{ws_id}/files/{path:path}")
async def download_workspace_file(
    ws_id: str,
    path: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Download a single file from a cloud workspace."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    try:
        if target.space_id:
            data = await _shared_download(target.space_id, path)
        else:
            data = await download_file(
                user_id=user.user_id,
                folder_id=target.folder_id,
                conversation_id=target.conversation_id,
                path=path,
            )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    except (PathNotFound, NotAFile) as e:
        raise NotFoundError("文件不存在") from e

    filename = path.rsplit("/", 1)[-1] or "download"
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers=download_headers(filename),
    )


@router.delete("/{ws_id}/files/{path:path}", response_model=StatusResponse)
async def delete_workspace_file(
    ws_id: str,
    path: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Delete a file or directory from a cloud workspace."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    _require_shared_write(target)
    try:
        async with workspace_lock(_storage_key(user.user_id, target)):
            if target.space_id:
                await _shared_delete(target.space_id, path)
                await shared_svc.record_file_change(
                    space_id=target.space_id,
                    actor_user_id=user.user_id,
                    actor_via="user",
                    action="file_deleted",
                    path=path,
                )
            else:
                await delete_file(
                    user_id=user.user_id,
                    folder_id=target.folder_id,
                    conversation_id=target.conversation_id,
                    path=path,
                )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    except PathNotFound as e:
        raise NotFoundError("文件不存在") from e
    return StatusResponse()


@router.post("/{ws_id}/move", response_model=StatusResponse)
async def move_workspace_file(
    ws_id: str,
    body: MoveFileRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Move/rename a file or directory within a cloud workspace."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    _require_shared_write(target)
    try:
        async with workspace_lock(_storage_key(user.user_id, target)):
            if target.space_id:
                await _shared_move(target.space_id, body.src, body.dst)
                await shared_svc.record_file_change(
                    space_id=target.space_id,
                    actor_user_id=user.user_id,
                    actor_via="user",
                    action="file_moved",
                    path=body.dst,
                    detail={"src": body.src},
                )
            else:
                await move_file(
                    user_id=user.user_id,
                    folder_id=target.folder_id,
                    conversation_id=target.conversation_id,
                    src=body.src,
                    dst=body.dst,
                )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    except PathNotFound as e:
        raise NotFoundError("文件不存在") from e
    except AlreadyExists as e:
        raise ValidationError("已存在同名文件") from e
    return StatusResponse()


@router.post("/{ws_id}/dirs", response_model=StatusResponse)
async def create_workspace_dir(
    ws_id: str,
    body: CreateDirRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Create a directory in a cloud workspace."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    _require_shared_write(target)
    try:
        async with workspace_lock(_storage_key(user.user_id, target)):
            if target.space_id:
                await _shared_mkdir(target.space_id, body.path)
                await shared_svc.record_file_change(
                    space_id=target.space_id,
                    actor_user_id=user.user_id,
                    actor_via="user",
                    action="dir_created",
                    path=body.path,
                )
            else:
                await create_dir(
                    user_id=user.user_id,
                    folder_id=target.folder_id,
                    conversation_id=target.conversation_id,
                    path=body.path,
                )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    except AlreadyExists as e:
        raise ValidationError("已存在同名文件或文件夹") from e
    return StatusResponse()


@router.post("/{ws_id}/clone", response_model=CloneRepoResponse)
async def clone_repo_into_workspace(
    ws_id: str,
    body: CloneRepoRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Clone a public git repository into a cloud workspace (决策⑤)."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    _refuse_shared_extra(target)
    try:
        async with workspace_lock(_storage_key(user.user_id, target)):
            dest = await clone_repo(
                user_id=user.user_id,
                folder_id=target.folder_id,
                conversation_id=target.conversation_id,
                repo_url=body.repo_url,
                dest=body.dest,
            )
    except ValueError as e:
        raise ValidationError(str(e)) from e
    except CloneError as e:
        raise ValidationError(f"克隆失败：{e}") from e
    return CloneRepoResponse(path=dest)


# --- Workspace snapshots (axis-3: backup / kept versions / download) ---


@router.get("/{ws_id}/snapshots", response_model=SnapshotListResponse)
async def list_workspace_snapshots(
    ws_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """List a workspace's snapshots (newest first). Allowed for local too —
    snapshots are object-store backed and keyed by ws (§五)."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _refuse_shared_extra(target)
    refs = await list_snapshots(
        user_id=user.user_id,
        folder_id=target.folder_id,
        conversation_id=target.conversation_id,
    )
    return SnapshotListResponse(
        data=[SnapshotSummary.model_validate(r) for r in refs],
        total=len(refs),
    )


@router.post("/{ws_id}/snapshots", response_model=SnapshotSummary, status_code=201)
async def create_workspace_snapshot(
    ws_id: str,
    body: CreateSnapshotRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Take a manual snapshot of a cloud workspace (a ``label`` keeps it as a
    version). Local workspaces snapshot via the desktop archive channel, not
    here (§五), so they are rejected with 409."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    _refuse_shared_extra(target)
    async with workspace_lock(_storage_key(user.user_id, target)):
        ref = await create_snapshot(
            user_id=user.user_id,
            folder_id=target.folder_id,
            conversation_id=target.conversation_id,
            label=body.label,
        )
    return SnapshotSummary.model_validate(ref)


@router.post("/{ws_id}/snapshots/{snapshot_id}/restore", response_model=StatusResponse)
async def restore_workspace_snapshot(
    ws_id: str,
    snapshot_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Restore a cloud workspace to a snapshot (overwrites current files).

    Refused (409) for local workspaces: it would rewrite the unused server-side
    mirror, not the user's machine."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _require_cloud(target)
    _refuse_shared_extra(target)
    try:
        async with workspace_lock(_storage_key(user.user_id, target)):
            await restore_snapshot(
                user_id=user.user_id,
                folder_id=target.folder_id,
                conversation_id=target.conversation_id,
                snapshot_id=snapshot_id,
            )
    except SnapshotNotFound as e:
        raise NotFoundError("快照不存在") from e
    return StatusResponse()


@router.get("/{ws_id}/snapshots/{snapshot_id}/download")
async def download_workspace_snapshot(
    ws_id: str,
    snapshot_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    shared_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Download a snapshot archive (zip). Allowed for local too (read-only)."""
    target = await _resolve_owned_workspace(
        ws_id, user.user_id, conv_repo, folder_repo, shared_svc
    )
    _refuse_shared_extra(target)
    try:
        data = await read_snapshot(
            user_id=user.user_id,
            folder_id=target.folder_id,
            conversation_id=target.conversation_id,
            snapshot_id=snapshot_id,
        )
    except SnapshotNotFound as e:
        raise NotFoundError("快照不存在") from e
    filename = f"workspace-{snapshot_id}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers=download_headers(filename),
    )
