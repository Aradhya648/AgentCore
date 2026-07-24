"""Sidecar local identity — DB-safe stable ``user_id``.

Desktop ``initialize`` historically sent the literal alias ``\"local\"``. That
string is fine for audit (String column) and log context, but UUID-typed tables
(``documents`` / memory notes / …) reject it via asyncpg ``DataError``.

Resolve the alias to a deterministic UUID **before** any DB boundary so memory /
rules loads use a legal, stable identity without swallowing the type error.
"""

from __future__ import annotations

import uuid

#: Wire / desktop alias for the unbound local-sidecar principal.
LOCAL_USER_ALIAS = "local"

#: ``uuid5(NAMESPACE_URL, "agentcore:sidecar:local-user")`` — stable across
#: processes; never collides with random ``uuid4`` account ids.
LOCAL_USER_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "agentcore:sidecar:local-user"))


def resolve_sidecar_user_id(raw: str | None) -> str:
    """Map missing / ``\"local\"`` to :data:`LOCAL_USER_ID`; pass other ids through."""
    value = (raw or "").strip() or LOCAL_USER_ALIAS
    if value == LOCAL_USER_ALIAS:
        return LOCAL_USER_ID
    return value
