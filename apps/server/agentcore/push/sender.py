"""Push transport port + FCM v1 adapter (原生推送下发, 认证与会话 §十).

A :class:`PushSender` is pure transport: given device tokens + a notification it
delivers, and returns the tokens the provider rejected as *unregistered* so the caller
can prune them (the DB resolve + prune lives in :mod:`agentcore.push.notify`). This
mirrors the project's port/adapter posture (cf. ``ChatEventPublisher`` / ``AssetStorage``)
so FCM can be swapped (APNs direct, a test double) without touching trigger code.

The FCM adapter speaks the HTTP **v1** API with a service-account OAuth2 bearer. It needs
**no new dependency**: the bearer is minted by signing the service-account JWT with the
already-present ``python-jose`` (RS256) and exchanging it via the already-present
``httpx`` — so push adds nothing to the install footprint.
"""

from __future__ import annotations

import json
import time
from asyncio import Lock
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

from agentcore.config import settings
from agentcore.core.logging import get_logger

logger = get_logger(__name__)

# Service-account → access-token exchange (Google OAuth2 JWT-bearer flow).
_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
_HTTP_TIMEOUT = 10.0


@dataclass(frozen=True)
class PushNotification:
    """One notification to deliver. ``data`` values MUST be strings (FCM requirement);
    the client reads them on tap to deep-link (conversation_id / message_id / kind)."""

    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class PushSender(Protocol):
    async def send(self, tokens: Sequence[str], notification: PushNotification) -> list[str]:
        """Deliver ``notification`` to each token; return the tokens the provider
        reported STALE (unregistered/invalid) so the caller prunes them. Best-effort:
        a transport error logs and is swallowed (a missing push must never break a turn).
        """
        ...


class NullPushSender:
    """No-op sender (push disabled / unconfigured). Delivers nothing, prunes nothing."""

    async def send(self, tokens: Sequence[str], notification: PushNotification) -> list[str]:
        return []


class FcmPushSender:
    """FCM HTTP v1 sender with a cached service-account OAuth2 bearer.

    Sends one request per token (simple + lets us map each stale token precisely); for
    the low push volume here (a handful of devices per user, on durable pauses only)
    that is well within budget. A 404 / ``UNREGISTERED`` marks the token dead for pruning.
    """

    def __init__(
        self, *, project_id: str, client_email: str, private_key: str, token_uri: str
    ) -> None:
        self._project_id = project_id
        self._client_email = client_email
        self._private_key = private_key
        self._token_uri = token_uri or _DEFAULT_TOKEN_URI
        self._send_url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        self._access_token: str | None = None
        self._access_token_exp = 0.0
        self._token_lock = Lock()

    async def _bearer(self) -> str | None:
        """A valid access token, minted/cached. ``None`` if the exchange fails (callers
        then skip sending — degraded, not crashed). Serialized so a burst of pushes does
        one refresh, not N."""
        now = time.time()
        # 60s skew margin so an in-flight send never uses an about-to-expire token.
        if self._access_token and now < self._access_token_exp - 60:
            return self._access_token
        async with self._token_lock:
            now = time.time()
            if self._access_token and now < self._access_token_exp - 60:
                return self._access_token
            try:
                from jose import jwt  # local: only a configured FCM build needs jose here

                assertion = jwt.encode(
                    {
                        "iss": self._client_email,
                        "scope": _FCM_SCOPE,
                        "aud": self._token_uri,
                        "iat": int(now),
                        "exp": int(now) + 3600,
                    },
                    self._private_key,
                    algorithm="RS256",
                )
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                    resp = await client.post(
                        self._token_uri,
                        data={"grant_type": _JWT_BEARER_GRANT, "assertion": assertion},
                    )
                if resp.status_code != 200:
                    logger.warning(
                        "push.fcm_token_failed",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return None
                payload = resp.json()
                self._access_token = payload["access_token"]
                self._access_token_exp = now + float(payload.get("expires_in", 3600))
                return self._access_token
            except Exception as e:  # noqa: BLE001 — auth failure degrades to "no push"
                logger.warning("push.fcm_token_error", error=str(e))
                return None

    async def send(self, tokens: Sequence[str], notification: PushNotification) -> list[str]:
        if not tokens:
            return []
        bearer = await self._bearer()
        if not bearer:
            return []
        headers = {"Authorization": f"Bearer {bearer}"}
        dead: list[str] = []
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            for token in tokens:
                message = {
                    "token": token,
                    "notification": {
                        "title": notification.title,
                        "body": notification.body,
                    },
                }
                if notification.data:
                    message["data"] = notification.data
                try:
                    resp = await client.post(
                        self._send_url, headers=headers, json={"message": message}
                    )
                except Exception as e:  # noqa: BLE001 — one bad send never aborts the fan-out
                    logger.warning("push.fcm_send_error", error=str(e))
                    continue
                if resp.status_code == 200:
                    continue
                # 404 NOT_FOUND or an UNREGISTERED error = the app was uninstalled / token
                # rotated; mark it for pruning. Other non-2xx (quota, 5xx) are transient —
                # log and keep the token for the next attempt.
                if resp.status_code == 404 or "UNREGISTERED" in resp.text:
                    dead.append(token)
                else:
                    logger.warning(
                        "push.fcm_send_failed",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
        return dead


@lru_cache(maxsize=1)
def build_push_sender() -> PushSender:
    """The process-wide sender, chosen from config (cached — built once).

    Returns :class:`NullPushSender` when push is disabled OR the service-account file is
    missing/unreadable/malformed, so a misconfig degrades to "no push" rather than
    failing startup. ``project_id`` comes from settings or the service-account JSON.
    """
    if not settings.push_enabled:
        return NullPushSender()
    path = settings.fcm_service_account_path
    if not path:
        logger.warning("push.fcm_unconfigured")
        return NullPushSender()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return FcmPushSender(
            project_id=settings.fcm_project_id or data["project_id"],
            client_email=data["client_email"],
            private_key=data["private_key"],
            token_uri=data.get("token_uri", _DEFAULT_TOKEN_URI),
        )
    except Exception as e:  # noqa: BLE001 — a bad credential file must not crash boot
        logger.warning("push.fcm_init_failed", error=str(e))
        return NullPushSender()
