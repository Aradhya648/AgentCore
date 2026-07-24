"""Push device registration routes (原生推送设备注册, 认证与会话 §十).

A mobile (Capacitor) client registers its FCM device token so the backend can push when
an agent durably pauses for the user (plan_review / ask_user) while the app is gone.
Bearer-authenticated (the mobile origin). Tokens are per-user; re-registering the same
token MOVES it to the current user (upsert) and logout unregisters it.

- ``POST   /v1/devices``        register / refresh this device's token
- ``GET    /v1/devices``        this user's devices (token withheld) — manage / debug
- ``DELETE /v1/devices?token=`` unregister one token (logout)
"""

from fastapi import APIRouter, Depends

from agentcore.api.dependencies import AuthUser, get_push_device_repo
from agentcore.api.schemas import (
    DeviceListResponse,
    DeviceRegistration,
    DeviceSummary,
    StatusResponse,
)
from agentcore.db.models import PushDeviceRow
from agentcore.db.repositories import PushDeviceRepository

router = APIRouter(prefix="/devices", tags=["devices"])


def _summary(device: PushDeviceRow) -> DeviceSummary:
    # The raw token is a delivery secret — never echoed back to the client.
    return DeviceSummary(id=device.id, platform=device.platform, created_at=device.created_at)


@router.post("", response_model=StatusResponse)
async def register_device(
    body: DeviceRegistration,
    user: AuthUser,
    repo: PushDeviceRepository = Depends(get_push_device_repo),
):
    """Register (or refresh) this device's push token for the current user.

    Idempotent: upsert on the token, so re-registering after a token rotation or a new
    login simply moves the token to the current user instead of creating duplicates.
    """
    await repo.upsert(user_id=user.user_id, token=body.token, platform=body.platform)
    return StatusResponse()


@router.get("", response_model=DeviceListResponse)
async def list_devices(
    user: AuthUser,
    repo: PushDeviceRepository = Depends(get_push_device_repo),
):
    """The current user's registered devices (newest-first), tokens withheld."""
    devices = await repo.list_by_user(user.user_id)
    data = [_summary(d) for d in devices]
    return DeviceListResponse(data=data, total=len(data))


@router.delete("", response_model=StatusResponse)
async def unregister_device(
    token: str,
    user: AuthUser,
    repo: PushDeviceRepository = Depends(get_push_device_repo),
):
    """Unregister one of the current user's device tokens (logout).

    ``token`` is a query parameter (an FCM token contains URL-reserved characters, so a
    path segment is unsafe). Owner-scoped + idempotent: deleting an unknown / already-gone
    token still returns ok (the client's goal — "this device no longer receives" — holds).
    """
    await repo.delete(user_id=user.user_id, token=token)
    return StatusResponse()
