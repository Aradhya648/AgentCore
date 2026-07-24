"""Shared helpers for the API schema layer.

Kept in one private module so domain schema modules can share them. The package
``__init__`` keeps the historical ``from agentcore.api.schemas import X`` surface.
"""

from pathlib import PurePosixPath


def _avatar_url(user_id: str, avatar_key: str | None) -> str | None:
    """Derive the served avatar URL from the stored object key (or None).

    ``avatars/<id>/<hash>.webp`` → ``/v1/users/<id>/avatar?v=<hash>``: a relative
    path (client prefixes its API base) with the content hash as a cache-buster, so
    the served <img> changes exactly when the picture does. → api/routes/users.py.
    """
    if not avatar_key:
        return None
    version = PurePosixPath(avatar_key).stem
    return f"/v1/users/{user_id}/avatar?v={version}"
