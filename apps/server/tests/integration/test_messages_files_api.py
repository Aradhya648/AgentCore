"""IM chat-file download: CJK filenames must not 500 (Content-Disposition).

Regression for the ImageOff bug: bare ``filename="微信…"`` latin-1-crashes
Starlette ASGI encode on the download response, so Chinese-named images (common
from WeChat / Windows screenshots) never load for other members.
"""

from urllib.parse import quote

import httpx

from tests.integration.conftest import register_and_login


async def _user_id(client: httpx.AsyncClient) -> str:
    r = await client.get("/v1/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_chat_file_download_chinese_filename_ok(client, new_client, tmp_path, monkeypatch):
    """Upload + download a Chinese-named image; response headers must be latin-1-safe."""
    from agentcore.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    await register_and_login(client, "imfile_alice")
    alice_id = await _user_id(client)

    async with new_client() as bob:
        await register_and_login(bob, "imfile_bob")
        r = await bob.post("/v1/messages/chats/dm", json={"user_id": alice_id})
        assert r.status_code == 201, r.text
        chat_id = r.json()["id"]

        path = "attachments/uuid-1/微信图片.png"
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        put = await bob.put(
            f"/v1/messages/chats/{chat_id}/files/{quote(path, safe='/')}",
            content=png,
        )
        assert put.status_code == 200, put.text

        # Peer (Alice) fetches the same path — this is the ImageOff path.
        get = await client.get(
            f"/v1/messages/chats/{chat_id}/files/{quote(path, safe='/')}",
        )
        assert get.status_code == 200, get.text
        assert get.content == png
        cd = get.headers.get("content-disposition", "")
        assert "filename*=UTF-8''" in cd
        # Prove ASGI could encode the header (httpx already did; double-check bytes).
        cd.encode("latin-1")
