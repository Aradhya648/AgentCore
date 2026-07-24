"""Shared helper for the ORM model modules.

These modules were split out of a single ``models.py`` by domain; this private
module holds the row-id factory they all use so it stays defined once. ``Base`` is
intentionally NOT here — it lives in ``agentcore.db.base`` (the engine/session home)
and every model imports it from there.
"""

from uuid import uuid4


def _new_uuid() -> str:
    return str(uuid4())
