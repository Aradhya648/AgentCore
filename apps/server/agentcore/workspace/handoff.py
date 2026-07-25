"""Local→cloud handoff — archive the bound local workspace, snapshot it (P2e / e1).

The first leg of the 本地→云 交接 bridge (双模式工作区设计 §四). A local-mode
conversation's files live on the user's machine, so the post-turn OSS backup
(``conversation/service``) deliberately skips local mode — there is nothing on the
server to snapshot. This path closes that gap on demand: it asks the bound desktop
to pack its whole authorized root into one archive over the existing
``WorkspaceChannel`` (the same transport the file ops use), unpacks it into a
server-side staging dir, and hands that to the configured ``StorageProvider`` —
reusing the entire cloud snapshot machinery (list / restore / download) verbatim.

Scope (e1): snapshot upload only — for backup / cross-device. Running a cloud team
on the snapshot (e2) and returning results as a diff/PR (e3) are separate, later
legs that build on the snapshot this produces.
"""

from __future__ import annotations

import base64
import io
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.runtime.events import EventSink
from agentcore.runtime.interaction import default_interaction_registry
from agentcore.storage import SnapshotRef, build_storage_provider
from agentcore.workspace.channel import WorkspaceChannel, WorkspaceOp
from agentcore.workspace.locate import LocalBinding, workspace_storage_key
from agentcore.workspace.protocol import WorkspaceIOError

logger = get_logger(__name__)


def _unpack_archive(archive_b64: str, dest: Path) -> int:
    """Extract a base64 zip into ``dest`` (created), returning the raw archive size.

    Hardened against zip-slip: every member is resolved under ``dest`` and a member
    escaping it aborts the whole extraction, so a malformed/hostile desktop reply
    can never write outside the staging dir.
    """
    raw = base64.b64decode(archive_b64)
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise WorkspaceIOError(f"unsafe handoff archive member: {member}")
        zf.extractall(dest)
    return len(raw)


async def snapshot_local(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    binding: LocalBinding,
    sink: EventSink,
) -> SnapshotRef:
    """Archive the bound local workspace and snapshot it to object storage (e1).

    Issues a single ``ARCHIVE`` op over the channel (wide deadline — packing a repo
    is slow), unpacks the returned zip into a temp staging dir, and snapshots that
    dir under the conversation's storage key with a ``handoff:<ts>`` label so it is
    a kept version (never auto-pruned, alongside the cloud-mode manual versions).

    Reuses the channel transport and the snapshot machinery untouched. Raises a
    ``WorkspaceError`` if the desktop fails or drops (the channel maps it to a typed
    error), and always cleans up the staging dir.
    """
    channel = WorkspaceChannel(
        sink=sink,
        conversation_id=conversation_id,
        registry=default_interaction_registry(),
        timeout_seconds=settings.workspace_handoff_timeout_seconds,
        root_id=binding.root_id,
    )
    # Scope ARCHIVE to the workspace subpath (项目子目录 / 裸聊
    # ``conversations/<id>``)，zip 内路径保持工作区相对——与 LocalWorkspace 前缀口径一致。
    archive_args: dict[str, object] = {"ignore": True}
    if binding.subpath:
        archive_args["directory"] = binding.subpath
    value = await channel.request(
        WorkspaceOp.ARCHIVE,
        archive_args,
        timeout=settings.workspace_handoff_timeout_seconds,
    )
    archive_b64 = value.get("archive", "") if isinstance(value, dict) else ""
    if not archive_b64:
        raise WorkspaceIOError("desktop returned an empty handoff archive")

    staging = Path(tempfile.mkdtemp(prefix="agentcore-handoff-"))
    try:
        archive_bytes = _unpack_archive(str(archive_b64), staging)
        label = f"handoff:{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
        ref = await build_storage_provider().snapshot(
            staging,
            workspace_storage_key(
                user_id=user_id,
                folder_id=folder_id,
                conversation_id=conversation_id,
            ),
            label=label,
        )
        logger.info(
            "handoff.snapshot_created",
            conversation_id=conversation_id,
            snapshot_id=ref.snapshot_id,
            archive_bytes=archive_bytes,
            truncated=bool(value.get("truncated")) if isinstance(value, dict) else False,
        )
        return ref
    finally:
        shutil.rmtree(staging, ignore_errors=True)
