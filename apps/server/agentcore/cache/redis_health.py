"""Redis connectivity probe for readiness checks."""

from __future__ import annotations

import asyncio

from agentcore.config import settings
from agentcore.core.logging import get_logger

logger = get_logger(__name__)

_REDIS_PROBE_TIMEOUT_S = 2.0


async def redis_ready() -> bool:
    """Return whether Redis is reachable when ``rate_limit_backend=redis``.

    When the backend is ``memory``, Redis is optional and this returns ``True``.
    """
    if settings.rate_limit_backend != "redis":
        return True
    try:
        import redis

        def _ping() -> bool:
            client = redis.Redis.from_url(settings.redis_url)
            return bool(client.ping())

        return await asyncio.wait_for(
            asyncio.to_thread(_ping),
            timeout=_REDIS_PROBE_TIMEOUT_S,
        )
    except Exception as exc:
        logger.warning("redis.probe_failed", error=str(exc))
        return False
