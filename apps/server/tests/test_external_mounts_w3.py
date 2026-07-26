"""W3 session external mounts: routing, readonly refusal, grant store lifecycle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agentcore.workspace import grant_store
from agentcore.workspace.channel import WorkspaceChannel, WorkspaceOp
from agentcore.workspace.external_mounts import (
    ExternalMount,
    external_env_var,
    external_ns,
    parse_external_path,
    sanitize_alias,
    uniquify_alias,
)
from agentcore.workspace.local import LocalWorkspace
from agentcore.workspace.protocol import OutsideWorkspace, PathNotFound, WorkspaceIOError
from agentcore.workspace.server import ServerWorkspace


@pytest.fixture(autouse=True)
def _clear_grants():
    grant_store.clear_all_for_tests()
    yield
    grant_store.clear_all_for_tests()


def test_parse_external_path():
    assert parse_external_path("external/reports/a.xlsx") == ("reports", "a.xlsx")
    assert parse_external_path("external/reports") == ("reports", "")
    assert parse_external_path("attachments/x") is None
    assert parse_external_path("../evil") is None


def test_sanitize_and_uniquify_alias():
    assert sanitize_alias("6月报表")
    a = uniquify_alias("reports", {"reports"})
    assert a == "reports_2"


def test_grant_store_add_revoke_clear():
    m = grant_store.add_grant("c1", root_id="r1", label="报表", alias_hint="reports")
    assert m.alias == "reports"
    assert grant_store.list_grants("c1")[0].root_id == "r1"
    # Same root refreshes without duplicating
    m2 = grant_store.add_grant("c1", root_id="r1", label="报表2")
    assert m2.alias == "reports"
    assert len(grant_store.list_grants("c1")) == 1
    assert grant_store.revoke_grant("c1", alias="reports")
    assert grant_store.list_grants("c1") == []


@pytest.mark.asyncio
async def test_local_workspace_routes_external_read_and_rejects_write():
    channel = AsyncMock(spec=WorkspaceChannel)
    channel.root_id = "primary"
    channel.conversation_id = "c1"
    channel.request = AsyncMock(return_value="ok-content")
    ws = LocalWorkspace(channel)
    ws.attach_external_mounts(
        {
            "reports": ExternalMount(
                alias="reports", root_id="ext-r1", label="报表", mode="readonly"
            )
        }
    )
    out = await ws.read("external/reports/a.txt")
    assert out == "ok-content"
    channel.request.assert_awaited()
    call = channel.request.await_args
    assert call.args[0] == WorkspaceOp.READ
    assert call.args[1]["path"] == "a.txt"
    assert call.kwargs.get("root_id") == "ext-r1"

    with pytest.raises(OutsideWorkspace, match="只读"):
        await ws.write("external/reports/a.txt", "nope")


@pytest.mark.asyncio
async def test_local_workspace_unknown_external_alias():
    channel = AsyncMock(spec=WorkspaceChannel)
    channel.root_id = "primary"
    channel.conversation_id = "c1"
    ws = LocalWorkspace(channel)
    with pytest.raises(PathNotFound):
        await ws.read("external/missing/x.txt")


@pytest.mark.asyncio
async def test_server_workspace_external_readonly(tmp_path: Path):
    primary = tmp_path / "ws"
    primary.mkdir()
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "note.txt").write_text("hello", encoding="utf-8")

    class _Sandbox:
        async def execute(self, req):
            from agentcore.tools.sandbox.protocol import ExecutionResult

            return ExecutionResult(
                success=True, stdout="", stderr="", exit_code=0, duration_ms=0
            )

    ws = ServerWorkspace(primary, _Sandbox(), location="local")
    ws.attach_external_mounts(
        {
            "ext": ExternalMount(
                alias="ext",
                root_id="r",
                label="ext",
                abs_path=str(ext),
                mode="readonly",
            )
        }
    )
    assert await ws.read("external/ext/note.txt") == "hello"
    with pytest.raises(OutsideWorkspace, match="只读"):
        await ws.write("external/ext/note.txt", "x")
    entries = await ws.list("external/ext", "*")
    assert any(e.path == "external/ext/note.txt" for e in entries)


@pytest.mark.asyncio
async def test_server_workspace_model_path_no_dotdot_leak(tmp_path: Path):
    """list_tree / _model_path must not emit ``../`` when abs is under an external mount."""
    primary = tmp_path / "ws"
    primary.mkdir()
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "a.txt").write_text("x", encoding="utf-8")

    class _Sandbox:
        async def execute(self, req):
            from agentcore.tools.sandbox.protocol import ExecutionResult

            return ExecutionResult(
                success=True, stdout="", stderr="", exit_code=0, duration_ms=0
            )

    ws = ServerWorkspace(primary, _Sandbox(), location="local")
    ws.attach_external_mounts(
        {
            "ext": ExternalMount(
                alias="ext",
                root_id="r",
                label="ext",
                abs_path=str(ext),
                mode="readonly",
            )
        }
    )
    # Reverse-lookup without logical (the dangerous fallback path).
    mapped = ws._model_path(ext / "a.txt")
    assert mapped == "external/ext/a.txt"
    assert ".." not in mapped

    tree = await ws.list_tree("external/ext", max_depth=2)
    assert tree.entries
    for e in tree.entries:
        assert e.path.startswith("external/ext")
        assert ".." not in e.path


def test_external_env_var_name():
    assert external_env_var("my-reports") == "AGENTCORE_EXTERNAL_MY_REPORTS"
    assert external_ns("a", "b/c") == "external/a/b/c"


@pytest.mark.asyncio
async def test_local_organize_allows_move_rejects_write_and_permanent():
    channel = AsyncMock(spec=WorkspaceChannel)
    channel.root_id = "primary"
    channel.conversation_id = "c1"
    channel.request = AsyncMock(return_value=None)
    ws = LocalWorkspace(channel)
    ws.attach_external_mounts(
        {
            "desk": ExternalMount(
                alias="desk", root_id="ext-r1", label="桌面", mode="organize"
            )
        }
    )
    await ws.mkdir("external/desk/Docs")
    channel.request.assert_awaited()
    with pytest.raises(OutsideWorkspace, match="整理授权|不允许"):
        await ws.write("external/desk/a.txt", "nope")
    with pytest.raises(OutsideWorkspace, match="永久删除"):
        await ws.delete("external/desk/a.txt", permanent=True)


@pytest.mark.asyncio
async def test_server_organize_move_and_env_skips_organize(tmp_path: Path):
    primary = tmp_path / "ws"
    primary.mkdir()
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "a.txt").write_text("hello", encoding="utf-8")

    class _Sandbox:
        async def execute(self, req):
            from agentcore.tools.sandbox.protocol import ExecutionResult

            return ExecutionResult(
                success=True, stdout="", stderr="", exit_code=0, duration_ms=0
            )

    ws = ServerWorkspace(primary, _Sandbox(), location="local")
    ws.attach_external_mounts(
        {
            "ext": ExternalMount(
                alias="ext",
                root_id="r",
                label="ext",
                abs_path=str(ext),
                mode="organize",
            )
        }
    )
    await ws.mkdir("external/ext/Docs")
    await ws.move("external/ext/a.txt", "external/ext/Docs/a.txt")
    assert (ext / "Docs" / "a.txt").read_text(encoding="utf-8") == "hello"
    from agentcore.workspace.external_mounts import build_external_env

    assert build_external_env(ws._mounts) == {}


def test_grant_store_mode_upgrade():
    m = grant_store.add_grant(
        "c1", root_id="r1", label="桌面", alias_hint="desk", mode="readonly"
    )
    assert m.mode == "readonly"
    m2 = grant_store.add_grant(
        "c1", root_id="r1", label="桌面", mode="organize"
    )
    assert m2.alias == m.alias
    assert m2.mode == "organize"


@pytest.mark.asyncio
async def test_cloud_server_external_via_channel_read_and_organize():
    """Cloud ServerWorkspace (no abs_path) routes external ops via per-op root_id."""
    primary = Path(".")  # unused for external channel path

    class _Sandbox:
        async def execute(self, req):
            from agentcore.tools.sandbox.protocol import ExecutionResult

            return ExecutionResult(
                success=True, stdout="", stderr="", exit_code=0, duration_ms=0
            )

    channel = AsyncMock(spec=WorkspaceChannel)
    channel.root_id = ""
    channel.conversation_id = "c-cloud"
    channel.request = AsyncMock(return_value="hello-from-desktop")

    ws = ServerWorkspace(primary, _Sandbox(), location="server")
    assert ws.location == "server"  # worker_gate must stay off
    ws.attach_external_mounts(
        {
            "desk": ExternalMount(
                alias="desk", root_id="ext-desk", label="桌面", mode="organize"
            )
        }
    )
    ws.attach_external_channel(channel)

    out = await ws.read("external/desk/a.txt")
    assert out == "hello-from-desktop"
    call = channel.request.await_args
    assert call.args[0] == WorkspaceOp.READ
    assert call.args[1]["path"] == "a.txt"
    assert call.kwargs.get("root_id") == "ext-desk"

    channel.request = AsyncMock(return_value=None)
    await ws.mkdir("external/desk/Docs")
    mkdir_call = channel.request.await_args
    assert mkdir_call.args[0] == WorkspaceOp.MKDIR
    assert mkdir_call.kwargs.get("root_id") == "ext-desk"
    assert ws.dirty

    with pytest.raises(OutsideWorkspace, match="整理授权|不允许"):
        await ws.write("external/desk/a.txt", "nope")
    with pytest.raises(OutsideWorkspace, match="永久删除"):
        await ws.delete("external/desk/a.txt", permanent=True)


@pytest.mark.asyncio
async def test_cloud_server_external_without_channel_still_hard_rejects(tmp_path: Path):
    class _Sandbox:
        async def execute(self, req):
            from agentcore.tools.sandbox.protocol import ExecutionResult

            return ExecutionResult(
                success=True, stdout="", stderr="", exit_code=0, duration_ms=0
            )

    ws = ServerWorkspace(tmp_path, _Sandbox(), location="server")
    ws.attach_external_mounts(
        {
            "desk": ExternalMount(
                alias="desk", root_id="ext-desk", label="桌面", mode="readonly"
            )
        }
    )
    with pytest.raises(WorkspaceIOError, match="本机引擎外不可直读"):
        await ws.read("external/desk/a.txt")


@pytest.mark.asyncio
async def test_cloud_server_unknown_and_primary_paths(tmp_path: Path):
    """Non-external primary still Path-I/O; unknown external alias still PathNotFound."""

    class _Sandbox:
        async def execute(self, req):
            from agentcore.tools.sandbox.protocol import ExecutionResult

            return ExecutionResult(
                success=True, stdout="", stderr="", exit_code=0, duration_ms=0
            )

    (tmp_path / "note.txt").write_text("primary", encoding="utf-8")
    channel = AsyncMock(spec=WorkspaceChannel)
    channel.root_id = ""
    channel.conversation_id = "c1"
    channel.request = AsyncMock(return_value="should-not-be-called")

    ws = ServerWorkspace(tmp_path, _Sandbox(), location="server")
    ws.attach_external_mounts(
        {
            "desk": ExternalMount(
                alias="desk", root_id="ext-desk", label="桌面", mode="readonly"
            )
        }
    )
    ws.attach_external_channel(channel)

    assert await ws.read("note.txt") == "primary"
    channel.request.assert_not_awaited()

    with pytest.raises(PathNotFound):
        await ws.read("external/missing/x.txt")
    channel.request.assert_not_awaited()


def test_build_turn_backend_attaches_external_channel_for_cloud_grants(tmp_path, monkeypatch):
    """Cloud turn with grants wires attach_external_channel (root_id-only mounts)."""
    from agentcore.config import settings
    from agentcore.conversation.turn_backend import build_turn_backend
    from agentcore.runtime.events.sink import EventSink

    grant_store.add_grant("conv-cloud", root_id="r-ext", label="桌面", alias_hint="desk")
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    backend = build_turn_backend(
        user_id="u1",
        conversation_id="conv-cloud",
        folder_id=None,
        sink=EventSink(),
        local_binding=None,
    )
    assert isinstance(backend, ServerWorkspace)
    assert backend.location == "server"
    assert backend._external_bridge is not None  # noqa: SLF001
    assert "desk" in backend._mounts  # noqa: SLF001
    assert backend._mounts["desk"].root_id == "r-ext"  # noqa: SLF001
    assert backend._mounts["desk"].abs_path is None  # noqa: SLF001
