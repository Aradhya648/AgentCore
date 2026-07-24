"""Tests for workspace path policy (conversation scratch → directory).

Pins Folder 重构 To-Be: every conversation owns ``conv/<id>/`` scratch;
``folder_id`` is sidebar grouping only. ``data_dir`` is redirected to ``tmp_path``.
"""

from pathlib import Path

import pytest

from agentcore.config import settings
from agentcore.runtime.events import EventSink
from agentcore.runtime.interaction import (
    InteractionRegistry,
    default_interaction_registry,
)
from agentcore.workspace.local import LocalWorkspace
from agentcore.workspace.locate import (
    LocalBinding,
    WorkspaceId,
    build_local_workspace,
    build_server_workspace,
    build_workspace,
    format_workspace_id,
    parse_workspace_id,
    resolve_workspace_root,
    workspace_has_entries,
    workspace_storage_key,
)
from agentcore.workspace.server import ServerWorkspace


def test_foldered_conversation_shares_folder_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    root = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    assert root == tmp_path / "workspaces" / "u1" / "f1"
    assert root.is_dir()


def test_conversations_in_same_folder_share_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    r1 = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    r2 = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c2")
    assert r1 == r2


def test_ungrouped_conversations_get_independent_roots(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    r1 = resolve_workspace_root(user_id="u1", folder_id=None, conversation_id="c1")
    r2 = resolve_workspace_root(user_id="u1", folder_id=None, conversation_id="c2")
    assert r1 != r2
    assert r1 == tmp_path / "workspaces" / "u1" / "conv" / "c1"
    assert r1.parent.name == "conv"


def test_users_are_isolated_by_directory(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    a = resolve_workspace_root(user_id="alice", folder_id="f1", conversation_id="c1")
    b = resolve_workspace_root(user_id="bob", folder_id="f1", conversation_id="c1")
    assert a != b
    assert a.parent.name == "alice"  # <workspaces>/<user_id>/<folder_id>


def test_build_server_workspace_targets_resolved_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ws = build_server_workspace(user_id="u1", folder_id=None, conversation_id="c9")
    assert isinstance(ws, ServerWorkspace)
    assert ws.location == "server"


# --- cloud/local fork (双模式工作区 §七: 模式跟着文件在哪自动走) ----------------


def test_build_local_workspace_wires_channel_to_bound_root():
    """A binding yields a LocalWorkspace whose channel carries the desktop root_id."""
    sink = EventSink()
    registry = InteractionRegistry()
    ws = build_local_workspace(
        binding=LocalBinding(root_id="root-xyz", root_label="myproj"),
        sink=sink,
        conversation_id="c1",
        registry=registry,
        timeout_seconds=12.5,
    )
    assert isinstance(ws, LocalWorkspace)
    assert ws.location == "local"
    assert ws.root_label == "myproj"
    chan = ws._channel  # noqa: SLF001 - test-only wiring inspection
    assert chan.root_id == "root-xyz"
    assert chan.conversation_id == "c1"
    assert chan.sink is sink
    assert chan.registry is registry
    assert chan.timeout_seconds == 12.5


def test_build_local_workspace_defaults_to_shared_registry_and_timeout():
    """Omitted deps fall back to the process registry + configured op timeout."""
    ws = build_local_workspace(
        binding=LocalBinding(root_id="r1"),
        sink=EventSink(),
        conversation_id="c1",
    )
    chan = ws._channel  # noqa: SLF001 - test-only wiring inspection
    assert chan.registry is default_interaction_registry()
    assert chan.timeout_seconds == settings.workspace_op_timeout_seconds
    assert ws.root_label == "workspace"


def test_build_workspace_picks_local_when_bound():
    ws = build_workspace(
        user_id="u1",
        folder_id="f1",
        conversation_id="c1",
        sink=EventSink(),
        local_binding=LocalBinding(root_id="root-1"),
    )
    assert isinstance(ws, LocalWorkspace)
    assert ws.location == "local"


def test_build_workspace_falls_back_to_cloud_when_unbound(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ws = build_workspace(
        user_id="u1",
        folder_id="f1",
        conversation_id="c1",
        sink=EventSink(),
        local_binding=None,
    )
    assert isinstance(ws, ServerWorkspace)
    assert ws.location == "server"


# --- storage key (mirrors the on-disk layout for snapshots) ---


def test_storage_key_folder_project():
    key = workspace_storage_key(user_id="u1", folder_id="f1", conversation_id="c1")
    assert key == "workspaces/u1/f1"


def test_storage_key_ungrouped_space():
    key = workspace_storage_key(user_id="u1", folder_id=None, conversation_id="c1")
    assert key == "workspaces/u1/conv/c1"


def test_storage_key_mirrors_on_disk_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    root = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    key = workspace_storage_key(user_id="u1", folder_id="f1", conversation_id="c1")
    assert root == Path(settings.data_dir) / key


# --- public workspace id (the /v1/workspaces addressing token) ---


def test_format_workspace_id_folder_vs_conv():
    assert format_workspace_id(folder_id="f1", conversation_id="c1") == "folder:f1"
    assert format_workspace_id(folder_id=None, conversation_id="c1") == "conv:c1"


def test_parse_workspace_id_round_trips():
    assert parse_workspace_id("conv:c1") == WorkspaceId(kind="conv", ident="c1")
    assert parse_workspace_id("folder:f9") == WorkspaceId(kind="folder", ident="f9")
    parsed = parse_workspace_id(format_workspace_id(folder_id="f9", conversation_id="c9"))
    assert parsed == WorkspaceId(kind="folder", ident="f9")


def test_parse_workspace_id_accepts_uuid_idents():
    wid = "11111111-2222-3333-4444-555555555555"
    assert parse_workspace_id(f"folder:{wid}").ident == wid


def test_parse_workspace_id_rejects_malformed():
    for bad in ("", "folder", "folder:", ":f1", "team:f1", "folder:a/b", "conv/c1"):
        with pytest.raises(ValueError, match="非法工作区"):
            parse_workspace_id(bad)


def test_workspace_has_entries_false_when_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    assert not workspace_has_entries(user_id="u1", folder_id=None, conversation_id="c1")
    assert not (tmp_path / "workspaces" / "u1" / "conv" / "c1").exists()


def test_workspace_has_entries_false_when_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    assert not workspace_has_entries(user_id="u1", folder_id="f1", conversation_id="c1")


def test_workspace_has_entries_true_when_non_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    root = resolve_workspace_root(user_id="u1", folder_id="f1", conversation_id="c1")
    (root / "note.txt").write_text("hi", encoding="utf-8")
    assert workspace_has_entries(user_id="u1", folder_id="f1", conversation_id="c1")
