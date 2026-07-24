"""Sidecar local identity resolves the ``local`` alias to a DB-safe UUID."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from agentcore.sidecar.identity import (
    LOCAL_USER_ALIAS,
    LOCAL_USER_ID,
    resolve_sidecar_user_id,
)
from agentcore.sidecar.server import SidecarServer


def _recorder() -> tuple[list[dict[str, Any]], Any]:
    sent: list[dict[str, Any]] = []

    async def write_line(line: str) -> None:
        sent.append(json.loads(line))

    return sent, write_line


def test_local_user_id_is_uuid():
    uuid.UUID(LOCAL_USER_ID)
    assert str(
        uuid.uuid5(uuid.NAMESPACE_URL, "agentcore:sidecar:local-user")
    ) == LOCAL_USER_ID


def test_resolve_maps_local_alias_and_empty():
    assert resolve_sidecar_user_id(LOCAL_USER_ALIAS) == LOCAL_USER_ID
    assert resolve_sidecar_user_id(None) == LOCAL_USER_ID
    assert resolve_sidecar_user_id("") == LOCAL_USER_ID
    assert resolve_sidecar_user_id("  local  ") == LOCAL_USER_ID


def test_resolve_passes_through_real_ids():
    uid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    assert resolve_sidecar_user_id(uid) == uid
    assert resolve_sidecar_user_id("u") == "u"


def test_initialize_binds_local_alias_to_uuid(tmp_path):
    sent, write_line = _recorder()
    server = SidecarServer(write_line)
    root = tmp_path / "ws"
    root.mkdir()

    asyncio.run(
        server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "userId": LOCAL_USER_ALIAS,
                        "workspaceRoot": str(root),
                    },
                }
            )
        )
    )

    resp = next(m for m in sent if m.get("id") == 1)
    assert "result" in resp
    assert "error" not in resp
    assert server._user_id == LOCAL_USER_ID  # noqa: SLF001 — binding under test


def test_initialize_missing_user_id_defaults_to_local_uuid(tmp_path):
    sent, write_line = _recorder()
    server = SidecarServer(write_line)
    root = tmp_path / "ws"
    root.mkdir()

    asyncio.run(
        server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"workspaceRoot": str(root)},
                }
            )
        )
    )

    resp = next(m for m in sent if m.get("id") == 1)
    assert "result" in resp
    assert server._user_id == LOCAL_USER_ID  # noqa: SLF001
