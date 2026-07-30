"""Workspace files (bring files in / take results out: 文件进出·先上传)."""

import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, Query, Request, Response

from agentcore.api.dependencies import (
    AuthUser,
    get_conversation_repo,
)
from agentcore.api.download_headers import download_headers
from agentcore.api.schemas import (
    CloneRepoRequest,
    CloneRepoResponse,
    CreateDirRequest,
    ExportDocxRequest,
    ExportDocxResponse,
    MoveFileRequest,
    StatusResponse,
    UploadFileResponse,
    WorkspaceEditDoc,
    WorkspaceFileEntry,
    WorkspaceFileListResponse,
    WorkspaceWriteRequest,
    WorkspaceWriteResult,
)
from agentcore.config import settings
from agentcore.core.errors import NotFoundError, ValidationError
from agentcore.db.models import Conversation
from agentcore.db.repositories import ConversationRepository
from agentcore.docs_export.workspace_export import ExportMarkdownError, export_markdown_path
from agentcore.workspace.files import (
    create_dir,
    delete_file,
    download_file,
    list_files,
    move_file,
    read_file_for_edit,
    upload_file,
    write_file_text,
)
from agentcore.workspace.git import CloneError, clone_repo
from agentcore.workspace.locate import build_server_workspace, workspace_storage_key
from agentcore.workspace.locks import workspace_lock
from agentcore.workspace.protocol import (
    AlreadyExists,
    NotAFile,
    NotUTF8,
    OutsideWorkspace,
    PathNotFound,
)

from ._helpers import _get_owned_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


@asynccontextmanager
async def _conv_workspace_lock(
    conv: Conversation,
    *,
    user_id: str,
) -> AsyncIterator[None]:
    """Lock a conversation's scratch workspace for a creating panel op."""
    key = workspace_storage_key(
        user_id=user_id, folder_id=conv.folder_id, conversation_id=conv.id
    )
    async with workspace_lock(key):
        yield


@router.get("/{conversation_id}/workspace/files", response_model=WorkspaceFileListResponse)
async def list_workspace_files(
    conversation_id: str,
    user: AuthUser,
    recursive: bool = Query(False),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """List the files in the conversation's scratch workspace (top level or recursive)."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    entries = await list_files(
        user_id=user.user_id,
        folder_id=conv.folder_id,
        conversation_id=conv.id,
        recursive=recursive,
    )
    return WorkspaceFileListResponse(
        data=[WorkspaceFileEntry.model_validate(e) for e in entries],
        total=len(entries),
    )


@router.put("/{conversation_id}/workspace/files/{path:path}", response_model=UploadFileResponse)
async def upload_workspace_file(
    conversation_id: str,
    path: str,
    request: Request,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Upload (create/overwrite) a workspace file from the raw request body.

    The body is the file bytes (no multipart); ``path`` is the workspace-relative
    target. Bounded by ``workspace_upload_max_bytes`` so one request can't exhaust
    memory. A path that escapes the workspace is rejected (422).
    """
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)

    max_bytes = settings.workspace_upload_max_bytes
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise ValidationError(f"文件超出 {max_bytes} 字节的上传上限")
    data = await request.body()
    if len(data) > max_bytes:
        raise ValidationError(f"文件超出 {max_bytes} 字节的上传上限")

    try:
        async with _conv_workspace_lock(conv, user_id=user.user_id):
            written = await upload_file(
                user_id=user.user_id,
                folder_id=conv.folder_id,
                conversation_id=conv.id,
                path=path,
                data=data,
            )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    return UploadFileResponse(path=path, size_bytes=written)


@router.post(
    "/{conversation_id}/workspace/export-docx",
    response_model=ExportDocxResponse,
)
async def export_conversation_workspace_docx(
    conversation_id: str,
    body: ExportDocxRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Export a conversation-workspace Markdown file to a sibling ``.docx``."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    try:
        async with _conv_workspace_lock(conv, user_id=user.user_id):
            backend = build_server_workspace(
                user_id=user.user_id,
                folder_id=conv.folder_id,
                conversation_id=conv.id,
            )
            result = await export_markdown_path(backend, body.path)
    except ExportMarkdownError as e:
        raise ValidationError(e.message) from e
    return ExportDocxResponse(
        path=result.output_path,
        source_path=result.source_path,
        size_bytes=result.size_bytes,
        warnings=list(result.warnings),
    )


@router.get(
    "/{conversation_id}/workspace/edit/{path:path}",
    response_model=WorkspaceEditDoc,
)
async def read_workspace_file_for_edit(
    conversation_id: str,
    path: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Read a workspace file for in-panel editing (full text + mtime CAS baseline).

    Distinct from the raw-bytes download (preview, truncated): editing needs the whole
    file or a save would drop the tail.
    """
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    try:
        text, mtime_ms, eol = await read_file_for_edit(
            user_id=user.user_id,
            folder_id=conv.folder_id,
            conversation_id=conv.id,
            path=path,
        )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    except (PathNotFound, NotAFile) as e:
        raise NotFoundError("文件不存在") from e
    except NotUTF8 as e:
        raise ValidationError("文件不是 UTF-8 文本，无法编辑") from e
    return WorkspaceEditDoc(text=text, mtime_ms=mtime_ms, eol=eol)


@router.put(
    "/{conversation_id}/workspace/edit/{path:path}",
    response_model=WorkspaceWriteResult,
)
async def write_workspace_file(
    conversation_id: str,
    path: str,
    body: WorkspaceWriteRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Conditionally write editor text back to a workspace file (mtime CAS).

    The write-time CAS (``baseline_mtime_ms``) makes a save that raced an Agent turn
    return ``conflict`` instead of clobbering it.
    """
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)

    max_bytes = settings.workspace_upload_max_bytes
    if len(body.content.encode("utf-8")) > max_bytes:
        raise ValidationError(f"文件超出 {max_bytes} 字节的上传上限")

    try:
        async with _conv_workspace_lock(conv, user_id=user.user_id):
            ok, mtime_ms = await write_file_text(
                user_id=user.user_id,
                folder_id=conv.folder_id,
                conversation_id=conv.id,
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


@router.get("/{conversation_id}/workspace/files/{path:path}")
async def download_workspace_file(
    conversation_id: str,
    path: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Download a single file from the conversation's scratch workspace."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    try:
        data = await download_file(
            user_id=user.user_id,
            folder_id=conv.folder_id,
            conversation_id=conv.id,
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


@router.delete("/{conversation_id}/workspace/files/{path:path}", response_model=StatusResponse)
async def delete_workspace_file(
    conversation_id: str,
    path: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Delete a file or directory from the conversation's scratch workspace."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    key = workspace_storage_key(
        user_id=user.user_id, folder_id=conv.folder_id, conversation_id=conv.id
    )
    try:
        async with workspace_lock(key):
            await delete_file(
                user_id=user.user_id,
                folder_id=conv.folder_id,
                conversation_id=conv.id,
                path=path,
            )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    except PathNotFound as e:
        raise NotFoundError("文件不存在") from e
    return StatusResponse()


@router.post("/{conversation_id}/workspace/move", response_model=StatusResponse)
async def move_workspace_file(
    conversation_id: str,
    body: MoveFileRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Move/rename a file or directory within the conversation's scratch workspace."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    key = workspace_storage_key(
        user_id=user.user_id, folder_id=conv.folder_id, conversation_id=conv.id
    )
    try:
        async with workspace_lock(key):
            await move_file(
                user_id=user.user_id,
                folder_id=conv.folder_id,
                conversation_id=conv.id,
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


@router.post("/{conversation_id}/workspace/dirs", response_model=StatusResponse)
async def create_workspace_dir(
    conversation_id: str,
    body: CreateDirRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Create a directory in the conversation's scratch workspace."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    try:
        async with _conv_workspace_lock(conv, user_id=user.user_id):
            await create_dir(
                user_id=user.user_id,
                folder_id=conv.folder_id,
                conversation_id=conv.id,
                path=body.path,
            )
    except OutsideWorkspace as e:
        raise ValidationError("路径非法：超出工作区范围") from e
    except AlreadyExists as e:
        raise ValidationError("已存在同名文件或文件夹") from e
    return StatusResponse()


@router.post("/{conversation_id}/workspace/clone", response_model=CloneRepoResponse)
async def clone_repo_into_workspace(
    conversation_id: str,
    body: CloneRepoRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Clone a public git repository into the conversation's scratch workspace (决策⑤)."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    try:
        async with _conv_workspace_lock(conv, user_id=user.user_id):
            dest = await clone_repo(
                user_id=user.user_id,
                folder_id=conv.folder_id,
                conversation_id=conv.id,
                repo_url=body.repo_url,
                dest=body.dest,
            )
    except ValueError as e:
        raise ValidationError(str(e)) from e
    except CloneError as e:
        raise ValidationError(f"克隆失败：{e}") from e
    return CloneRepoResponse(path=dest)
