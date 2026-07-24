"""User media routes — avatar upload / delete (self) + public serve (头像).

On upload the bytes are re-encoded to a small square WebP (``avatars.py``) and kept
as a single content-addressed object in asset storage (``storage/assets.py``); only
the key lives on the user row. Serving is a **public** endpoint so a plain
``<img src>`` works without cookies — an avatar is non-secret and is already shown
to teammates (IM / rosters) — while upload/delete are self-only (``AuthUser``).
The served URL (with a content-hash cache-buster) is derived in
``UserResponse.avatar_url``.
"""

from fastapi import APIRouter, Depends, Request, Response

from agentcore.api.dependencies import AuthUser, get_asset_storage, get_user_repo
from agentcore.api.schemas import UserResponse
from agentcore.avatars import avatar_key, process_avatar
from agentcore.config import settings
from agentcore.core.errors import NotFoundError, ValidationError
from agentcore.db.repositories import UserRepository
from agentcore.storage.assets import AssetStorage

router = APIRouter(prefix="/users", tags=["users"])

# The object is immutable (content-addressed key) and the URL's ?v=<hash> changes on
# update, so a far-future cache never serves a stale picture.
_AVATAR_CACHE_CONTROL = "public, max-age=31536000, immutable"


@router.post("/me/avatar", response_model=UserResponse)
async def upload_my_avatar(
    request: Request,
    user: AuthUser,
    users: UserRepository = Depends(get_user_repo),
    assets: AssetStorage = Depends(get_asset_storage),
):
    """Upload the signed-in user's avatar (头像上传).

    Raw image bytes in the body (no multipart) — the client sends the picture file
    directly. The bytes are re-encoded to a square WebP, stored under a content-
    addressed key, and the superseded object is removed. 422 if the body isn't a
    decodable image or exceeds ``avatar_upload_max_bytes``.
    """
    max_bytes = settings.avatar_upload_max_bytes
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise ValidationError(f"图片超出 {max_bytes} 字节的上传上限")
    data = await request.body()
    if not data:
        raise ValidationError("请求体为空")
    if len(data) > max_bytes:
        raise ValidationError(f"图片超出 {max_bytes} 字节的上传上限")

    processed = process_avatar(data)  # 422 on a non-image
    key = avatar_key(user.user_id, processed)
    await assets.put(key, processed, content_type="image/webp")

    old_key = user.avatar_key
    updated = await users.set_avatar(user.user_id, key)
    if updated is None:  # pragma: no cover - the authed user always exists
        raise NotFoundError("用户不存在")
    # Best-effort GC of the prior object (skip when the re-upload was byte-identical).
    if old_key and old_key != key:
        await assets.delete(old_key)
    return UserResponse.from_user(updated)


@router.delete("/me/avatar", response_model=UserResponse)
async def delete_my_avatar(
    user: AuthUser,
    users: UserRepository = Depends(get_user_repo),
    assets: AssetStorage = Depends(get_asset_storage),
):
    """Remove the signed-in user's avatar (恢复默认头像).

    Idempotent: with no avatar set it still returns 200 with the unchanged user.
    """
    old_key = user.avatar_key
    updated = await users.set_avatar(user.user_id, None)
    if updated is None:  # pragma: no cover - the authed user always exists
        raise NotFoundError("用户不存在")
    if old_key:
        await assets.delete(old_key)
    return UserResponse.from_user(updated)


@router.get("/{user_id}/avatar")
async def get_user_avatar(
    user_id: str,
    users: UserRepository = Depends(get_user_repo),
    assets: AssetStorage = Depends(get_asset_storage),
):
    """Serve a user's avatar image (**public**, no auth).

    Avatars are non-secret and shown to teammates; a plain ``<img>`` can't carry the
    auth cookie cross-origin, so this stays open. 404 when the user has no avatar (or
    the object is missing). Always WebP (the only format the upload stores).
    """
    target = await users.get_by_id(user_id)
    if target is None or not target.avatar_key:
        raise NotFoundError("头像不存在")
    data = await assets.get(target.avatar_key)
    if data is None:
        # Key points at a vanished object (storage pruned) — behave as "no avatar".
        raise NotFoundError("头像不存在")
    return Response(
        content=data,
        media_type="image/webp",
        headers={"Cache-Control": _AVATAR_CACHE_CONTROL},
    )
