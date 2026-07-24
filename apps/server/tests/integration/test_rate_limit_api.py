"""Integration test: the per-user message-send rate limit gates a new turn (429).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable.
Saturates the in-memory message limiter for the authenticated user, then asserts the
turn-starting endpoint refuses the next turn with 429 + ``RATE_LIMITED`` (and a
``Retry-After`` header) before any SSE stream / LLM call begins (成本配额与计费.md
§一). Pre-filling the limiter keeps the test free of real LLM calls while proving
the route actually consults it.

The shared conftest disables rate limiting process-globally (auth counters are
process-global and would accumulate across the suite's many auth POSTs). These tests
re-enable it *after* registering/logging in, so only the message gate is exercised —
the auth POSTs are never throttled, and the autouse fixture restores the flag after.
"""

from agentcore.config import settings
from agentcore.core.types import new_id
from agentcore.db.repositories import ConversationRepository
from agentcore.middleware.rate_limit import message_rate_limiter
from tests.integration.conftest import register_and_login


async def _make_conversation(session_factory, *, user_id: str) -> str:
    async with session_factory() as session:
        conv = await ConversationRepository(session).create(user_id=user_id, title="t")
        return conv.id


def _saturate(user_id: str) -> None:
    """Fill the per-user message limiter so the next request is over the cap. The
    key is the fresh user's id, so it never collides with other tests."""
    message_rate_limiter.reset()
    for _ in range(settings.user_message_rate_limit_max):
        message_rate_limiter.check(user_id)


async def test_send_message_blocked_when_rate_limited(client, make_invite, session_factory):
    code = await make_invite("INV-RATE")
    user_id = await register_and_login(client, code, "rateuser")
    conv_id = await _make_conversation(session_factory, user_id=user_id)

    # Re-enable rate limiting (the suite disables it globally) and saturate this
    # user's bucket so the next send trips the gate before the stream / LLM call.
    settings.rate_limit_enabled = True
    _saturate(user_id)

    r = await client.post(f"/v1/conversations/{conv_id}/messages", json={"content": "hi"})

    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert r.headers.get("retry-after")


async def test_rate_limit_precedes_ownership_check(client, make_invite, session_factory):
    # Rate limiting is the outermost gate: a saturated account hitting a
    # conversation it doesn't own still gets 429 (not 404), shedding load before
    # any resource-specific DB work.
    code = await make_invite("INV-RATE-OWN")
    user_id = await register_and_login(client, code, "rateowner")

    settings.rate_limit_enabled = True
    _saturate(user_id)

    r = await client.post(f"/v1/conversations/{new_id()}/messages", json={"content": "hi"})

    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "RATE_LIMITED"
