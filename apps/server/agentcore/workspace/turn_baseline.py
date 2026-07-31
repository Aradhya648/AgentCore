"""A1+ turn baseline snapshot — best-effort freeze before writes.

Cloud (``run_and_persist``): labeled OSS/FS snapshot, id → ``messages.baseline_snapshot_id``.
Local (sidecar ``_run_turn``): zip beside the workspace at
``AgentCore/baselines/{message_id}.zip`` (id = message_id; no DB required).

失败 / 超限 / 超时只打日志，绝不阻断回合；桌面降级 A1 工具参数预览。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.storage._archive import ArchiveLimitError, zip_dir
from agentcore.workspace.protocol import WorkspaceBackend
from agentcore.workspace.snapshots import create_snapshot
from agentcore.workspace.stage_dirs import BASELINES_REL

logger = get_logger(__name__)

# Align desktop handoff ARCHIVE_MAX_* (apps/desktop/.../fs/constants.ts).
LOCAL_BASELINE_MAX_FILES = 20_000
LOCAL_BASELINE_MAX_BYTES = 100 * 1024 * 1024  # 100 MiB raw
LOCAL_BASELINE_TIMEOUT_S = 60.0


def local_baseline_path(workspace_root: Path, snapshot_id: str) -> Path:
    """``AgentCore/baselines/{snapshot_id}.zip`` under the bound workspace root."""
    return workspace_root / Path(*BASELINES_REL.split("/")) / f"{snapshot_id}.zip"


async def maybe_capture_turn_baseline(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    message_id: str,
    backend: WorkspaceBackend,
    workspace_root: Path | None = None,
) -> str | None:
    """Snapshot the workspace before the turn mutates it. Returns snapshot id or None.

    ``backend.location == "server"`` → cloud labeled snapshot (+ DB id stamp).
    ``backend.location == "local"`` → local zip under ``workspace_root`` (sidecar).
    """
    if backend.location == "local":
        if workspace_root is None:
            return None
        return await _capture_local_baseline(
            workspace_root=workspace_root,
            conversation_id=conversation_id,
            message_id=message_id,
        )
    if backend.location != "server":
        return None
    return await _capture_cloud_baseline(
        user_id=user_id,
        folder_id=folder_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )


async def _capture_cloud_baseline(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    message_id: str,
) -> str | None:
    if not settings.workspace_snapshot_enabled:
        return None
    label = f"turn-baseline:{message_id}"
    try:
        ref = await create_snapshot(
            user_id=user_id,
            folder_id=folder_id,
            conversation_id=conversation_id,
            label=label,
        )
    except Exception:
        logger.warning(
            "turn.baseline_snapshot_failed",
            conversation_id=conversation_id,
            message_id=message_id,
            exc_info=True,
        )
        return None

    try:
        # Lazy import: avoid pulling db.repositories at module import (circular with runtime).
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories.messages import MessageRepository

        async with async_session_factory() as session:
            await MessageRepository(session).set_baseline_snapshot_id(
                message_id,
                conversation_id=conversation_id,
                snapshot_id=ref.snapshot_id,
            )
    except Exception:
        logger.warning(
            "turn.baseline_snapshot_id_persist_failed",
            conversation_id=conversation_id,
            message_id=message_id,
            snapshot_id=ref.snapshot_id,
            exc_info=True,
        )
        return ref.snapshot_id

    logger.info(
        "turn.baseline_snapshot",
        conversation_id=conversation_id,
        message_id=message_id,
        snapshot_id=ref.snapshot_id,
    )
    return ref.snapshot_id


def _zip_local_baseline_sync(workspace_root: Path, dest: Path) -> int:
    """Zip workspace into ``dest``; return byte size. Raises ArchiveLimitError."""
    data = zip_dir(
        workspace_root,
        max_files=LOCAL_BASELINE_MAX_FILES,
        max_bytes=LOCAL_BASELINE_MAX_BYTES,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Atomic-ish: write sibling then replace.
    tmp = dest.with_suffix(".zip.tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return len(data)


async def _capture_local_baseline(
    *,
    workspace_root: Path,
    conversation_id: str,
    message_id: str,
) -> str | None:
    """Best-effort local zip; snapshot id == message_id (path convention, no DB)."""
    dest = local_baseline_path(workspace_root, message_id)
    try:
        size = await asyncio.wait_for(
            asyncio.to_thread(_zip_local_baseline_sync, workspace_root, dest),
            timeout=LOCAL_BASELINE_TIMEOUT_S,
        )
    except TimeoutError:
        logger.warning(
            "turn.local_baseline_skipped",
            conversation_id=conversation_id,
            message_id=message_id,
            reason="timeout",
            timeout_s=LOCAL_BASELINE_TIMEOUT_S,
        )
        return None
    except ArchiveLimitError as e:
        logger.warning(
            "turn.local_baseline_skipped",
            conversation_id=conversation_id,
            message_id=message_id,
            reason=e.reason,
            file_count=e.file_count,
            total_bytes=e.total_bytes,
        )
        return None
    except Exception:
        logger.warning(
            "turn.local_baseline_failed",
            conversation_id=conversation_id,
            message_id=message_id,
            exc_info=True,
        )
        return None

    logger.info(
        "turn.local_baseline_snapshot",
        conversation_id=conversation_id,
        message_id=message_id,
        snapshot_id=message_id,
        size_bytes=size,
        path=str(dest),
    )
    return message_id
