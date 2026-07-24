"""Lightweight 3D vector — import-safe (no simulation package cycles)."""

from __future__ import annotations

from pydantic import BaseModel


class Vec3(BaseModel):
    """3D position on the town ground plane (Y-up wire coordinates).

    - ``x``: east (+) / west (-)
    - ``y``: height above ground (NPCs typically 0)
    - ``z``: south (+) / north (-)
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
