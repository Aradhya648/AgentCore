"""Resolve a conversation to its server-side workspace (cloud mode).

Path policy (项目即工作区):

- A conversation **in a project (folder)** shares that project's workspace:
  ``<data_dir>/workspaces/<user_id>/<folder_id>/`` (``folder:<id>``).
- A **裸聊** (ungrouped) gets its own independent scratch:
  ``<data_dir>/workspaces/<user_id>/conv/<conversation_id>/`` (``conv:<id>``).

User-scoped top segment keeps tenants isolated by directory; the traversal guard
inside ``ServerWorkspace`` then prevents escaping the resolved root. IDs are
server-generated UUIDs (not user input), so they are safe path segments.

This is the single place that maps "which conversation" → "which directory" (for
cloud) and "which conversation" → "which desktop root" (for local);
``conversation/service.py`` calls :func:`build_workspace` and injects the chosen
backend into the pipeline. The server-vs-local fork (双模式工作区 §七, "模式跟着
文件在哪自动走") lives here so tools and the engine stay backend-agnostic.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agentcore.config import settings
from agentcore.runtime.events import EventSink
from agentcore.runtime.interaction import default_interaction_registry
from agentcore.runtime.ports import ClientRequestBridge
from agentcore.tools.sandbox import create_sandbox
from agentcore.tools.sandbox.protocol import SandboxProvider
from agentcore.workspace.channel import WorkspaceChannel
from agentcore.workspace.local import LocalWorkspace
from agentcore.workspace.protocol import WorkspaceBackend
from agentcore.workspace.server import ServerWorkspace
from agentcore.workspace.shared_paths import resolve_shared_workspace_root

_WORKSPACES_SEGMENT = "workspaces"


def _workspaces_base() -> Path:
    return Path(settings.data_dir) / _WORKSPACES_SEGMENT


def _workspace_relpath(*, user_id: str, folder_id: str | None, conversation_id: str) -> str:
    """Workspace path relative to the workspaces base (POSIX).

    Project (= folder) conversations share ``<user>/<folder_id>/``; 裸聊 uses
    ``<user>/conv/<conversation_id>/``.
    """
    if folder_id:
        return f"{user_id}/{folder_id}"
    return f"{user_id}/conv/{conversation_id}"


# A workspace's stable public id — the addressing token for the first-class
# ``/v1/workspaces/{ws_id}`` API (文件中枢统一 Step 1). It encodes the same
# folder-vs-ungrouped fork as ``_workspace_relpath`` (the folder *is* the project
# space; an ungrouped conversation gets its own), so a id round-trips to exactly
# one workspace directory. ``:`` separates kind from the UUID — a valid single
# URL path segment that UUIDs never contain, so it needs no escaping.
_WORKSPACE_ID_SEP = ":"


@dataclass(frozen=True)
class WorkspaceId:
    """A parsed workspace id: folder project, bare-chat scratch, or shared space."""

    kind: Literal["folder", "conv", "shared"]
    ident: str


def format_workspace_id(*, folder_id: str | None, conversation_id: str) -> str:
    """Public workspace id: ``folder:<id>`` for a project, else ``conv:<id>``."""
    if folder_id:
        return f"folder{_WORKSPACE_ID_SEP}{folder_id}"
    return f"conv{_WORKSPACE_ID_SEP}{conversation_id}"


def format_shared_workspace_id(space_id: str) -> str:
    """Public workspace id for a shared space: ``shared:<space_id>``."""
    return f"shared{_WORKSPACE_ID_SEP}{space_id}"


def parse_workspace_id(ws_id: str) -> WorkspaceId:
    """Parse a public workspace id, or raise ``ValueError`` if malformed.

    Pure (no DB / owner check): the API layer resolves the ``ident`` against the
    user's folders/conversations (or shared-space membership) for authorization.
    Rejects unknown kinds and empty / slash-bearing idents so a id can address
    only one path segment.
    """
    kind, sep, ident = ws_id.partition(_WORKSPACE_ID_SEP)
    if not sep or not ident or "/" in ident or kind not in ("folder", "conv", "shared"):
        raise ValueError(f"非法工作区 id：{ws_id!r}")
    return WorkspaceId(kind=kind, ident=ident)  # type: ignore[arg-type]


def workspace_has_entries(*, user_id: str, folder_id: str | None, conversation_id: str) -> bool:
    """Whether the workspace dir exists and is non-empty — *without* creating it.

    Backs the hub enumeration's F1 filter (未分组空间只在真有文件时才列出, 文件中枢
    统一 §四). Uses the no-create path helper on purpose: resolving via the backend
    would ``mkdir`` an empty dir for every ungrouped conversation we probe.
    """
    root = workspace_root_path(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return root.is_dir() and any(root.iterdir())


def workspace_root_path(*, user_id: str, folder_id: str | None, conversation_id: str) -> Path:
    """The workspace directory path for a conversation — without creating it.

    The pure path helper behind :func:`resolve_workspace_root`; retention cleanup
    (决策⑦) needs the location to delete it, where creating-on-resolve would be
    wrong (and would resurrect a dir we are about to purge).
    """
    relpath = _workspace_relpath(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return _workspaces_base() / relpath


def resolve_workspace_root(*, user_id: str, folder_id: str | None, conversation_id: str) -> Path:
    """Return (creating if needed) the workspace directory for a conversation."""
    root = workspace_root_path(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_storage_key(*, user_id: str, folder_id: str | None, conversation_id: str) -> str:
    """The snapshot storage key for a conversation's workspace.

    Mirrors the on-disk layout under ``data_dir`` (``workspaces/<user>/<folder>``
    or ``workspaces/<user>/conv/<conversation>``) so a snapshot's object-store
    location reads the same as its filesystem location. The StorageProvider adds
    its own top-level prefix (``snapshots/``).
    """
    relpath = _workspace_relpath(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return f"{_WORKSPACES_SEGMENT}/{relpath}"


def _default_server_sandbox() -> SandboxProvider:
    """Cloud worker sandbox — gVisor when enabled, else subprocess."""
    return create_sandbox(
        location="server",
        gvisor_enabled=settings.gvisor_enabled,
        runsc_path=settings.gvisor_runsc_path,
        runtime_root=settings.gvisor_runtime_root,
    )


def build_server_workspace(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    sandbox: SandboxProvider | None = None,
) -> ServerWorkspace:
    """Construct the ``ServerWorkspace`` for a conversation's resolved root."""
    root = resolve_workspace_root(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    return ServerWorkspace(root=root, sandbox=sandbox or _default_server_sandbox())


# IM chat attachments live in their own top-level space, separate from the
# per-user conversation workspaces above: a chat is shared by many users, so it
# is keyed by ``chat_id`` (a server-minted UUID, safe as a single path segment)
# rather than nested under any one member's ``user_id``. Reusing ``ServerWorkspace``
# gives the same traversal guard and atomic writes for free (Stage 4 富消息).
_IM_SEGMENT = "im"


def chat_workspace_root_path(chat_id: str) -> Path:
    """The on-disk root for a chat's attachments — without creating it."""
    return _workspaces_base() / _IM_SEGMENT / chat_id


def build_chat_workspace(
    chat_id: str, *, sandbox: SandboxProvider | None = None
) -> ServerWorkspace:
    """Construct the ``ServerWorkspace`` rooted at a chat's attachment space.

    Callers must authorize membership *before* building this (the directory is
    created on resolve), so a non-member never materializes a chat's space.
    """
    root = chat_workspace_root_path(chat_id)
    root.mkdir(parents=True, exist_ok=True)
    return ServerWorkspace(root=root, sandbox=sandbox or _default_server_sandbox())


def build_shared_workspace(
    space_id: str, *, sandbox: SandboxProvider | None = None
) -> ServerWorkspace:
    """Construct a ``ServerWorkspace`` rooted at ``workspaces/shared/<space_id>/``.

    Callers must authorize membership *before* building (mkdir on resolve).
    """
    root = resolve_shared_workspace_root(space_id)
    return ServerWorkspace(root=root, sandbox=sandbox or _default_server_sandbox())


@dataclass(frozen=True)
class LocalBinding:
    """A conversation's binding to a desktop FS root (the local-mode marker).

    ``root_id`` is the desktop-generated handle for an authorized local directory
    (registered in ``apps/desktop/src/main/fs-service.ts``); ``root_label`` is its
    human-readable name, used for relative-path rendering so absolute local paths
    never leak into prompts. The *presence* of a binding is exactly what flips a
    conversation to local mode (§七); its absence means cloud.

    ``subpath`` (工作区对称化 D1a) is the workspace's sub-directory *within* the
    root. Empty = the folder is the root itself (an explicitly-added project). A
    non-empty single segment scopes a per-conversation workspace under a shared
    container root; ``LocalWorkspace`` prefixes it onto every op path so the engine
    and the user only ever see workspace-relative paths.
    """

    root_id: str
    root_label: str = "workspace"
    subpath: str = ""


def build_local_workspace(
    *,
    binding: LocalBinding,
    sink: EventSink,
    conversation_id: str,
    registry: ClientRequestBridge | None = None,
    timeout_seconds: float | None = None,
) -> LocalWorkspace:
    """Construct the ``LocalWorkspace`` for a conversation bound to a desktop root.

    Builds the per-turn ``WorkspaceChannel`` — the generalized approval-gate
    transport — over the live SSE ``sink`` plus the process-wide op registry (the
    same one the resolve endpoint settles), then wraps it. The channel carries
    ``binding.root_id`` so every op the engine issues runs against the right
    authorized directory on the user's machine. State (the suspended op Future)
    lives in the registry, so it must be the *shared* default unless a test injects
    its own.
    """
    channel = WorkspaceChannel(
        sink=sink,
        conversation_id=conversation_id,
        registry=registry or default_interaction_registry(),
        timeout_seconds=(
            settings.workspace_op_timeout_seconds if timeout_seconds is None else timeout_seconds
        ),
        root_id=binding.root_id,
    )
    return LocalWorkspace(
        channel,
        root_label=binding.root_label,
        execute_timeout_slack=settings.workspace_execute_timeout_slack_seconds,
        base_subpath=binding.subpath,
    )


def build_workspace(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    sink: EventSink,
    local_binding: LocalBinding | None,
    sandbox: SandboxProvider | None = None,
) -> WorkspaceBackend:
    """Pick a turn's backend: local when bound to a desktop root, else cloud.

    The single fork behind 双模式工作区 §七 ("模式跟着文件在哪自动走"): a resolved
    ``local_binding`` yields a desktop-backed ``LocalWorkspace``; its absence falls
    back to the server-hosted ``ServerWorkspace``. Both satisfy ``WorkspaceBackend``
    (the P0 seam), so the file tools and the engine run unchanged on either — the
    caller only has to decide *which* here, never *how* downstream.
    """
    if local_binding is not None:
        return build_local_workspace(
            binding=local_binding,
            sink=sink,
            conversation_id=conversation_id,
        )
    return build_server_workspace(
        user_id=user_id,
        folder_id=folder_id,
        conversation_id=conversation_id,
        sandbox=sandbox,
    )


def workspace_channel_for_tools(
    backend: WorkspaceBackend,
    *,
    sink: EventSink,
    conversation_id: str,
    registry: ClientRequestBridge | None = None,
) -> WorkspaceChannel | None:
    """The ``workspace_op_required`` channel tools use for desktop-held process ops.

    LocalWorkspace already owns a channel (file / execute ops) — reuse it so process
    ops share root_id + registry. Sidecar uses ServerWorkspace(location=local) with
    direct Path I/O and no channel; build one so ``terminal`` still leaves the
    short-lived sidecar for the desktop main process (双模式工作区 §四).
    Cloud server backends return ``None`` (terminal is not registered there).
    """
    if backend.location != "local":
        return None
    existing = getattr(backend, "_channel", None)
    if isinstance(existing, WorkspaceChannel):
        return existing
    return WorkspaceChannel(
        sink=sink,
        conversation_id=conversation_id,
        registry=registry or default_interaction_registry(),
        timeout_seconds=settings.workspace_op_timeout_seconds,
        root_id="",
    )
