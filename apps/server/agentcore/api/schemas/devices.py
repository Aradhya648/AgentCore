"""Push device registration (原生推送设备注册: FCM token, 认证与会话 §十) schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeviceRegistration(BaseModel):
    """A mobile client registering its push token (POST /v1/devices).

    ``platform`` is a closed set so a bad client can't seed an unroutable row; the
    backend currently delivers via FCM (Android + iOS-via-FCM), ``web`` is reserved.
    """

    token: str = Field(..., min_length=1, max_length=4096)
    platform: Literal["ios", "android", "web"]


class DeviceSummary(BaseModel):
    """One registered device (设备管理 / 测试用).

    Deliberately omits the raw ``token`` — it's a delivery secret, never echoed back.
    """

    id: str
    platform: str
    created_at: datetime


class DeviceListResponse(BaseModel):
    data: list[DeviceSummary]
    total: int
