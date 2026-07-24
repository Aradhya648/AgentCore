"""Town region graph and 3D anchor positions (M1 coordinate contract)."""

from __future__ import annotations

from agentcore.simulation.vec3 import Vec3

LOCATIONS: tuple[str, ...] = (
    "广场",
    "市场",
    "餐厅",
    "面包店",
    "公园",
    "住宅区",
    "镇政厅",
    "图书馆",
    "工坊",
    "码头",
    "心动营地",
)

LOCATION_NEIGHBORS: dict[str, list[str]] = {
    "广场": ["市场", "公园", "镇政厅", "图书馆"],
    "市场": ["广场", "面包店", "餐厅", "工坊"],
    "餐厅": ["市场", "住宅区", "码头"],
    "面包店": ["市场", "住宅区", "工坊"],
    "公园": ["广场", "住宅区", "码头", "图书馆", "心动营地"],
    "住宅区": ["餐厅", "面包店", "公园", "码头"],
    "镇政厅": ["广场", "图书馆"],
    "图书馆": ["广场", "公园", "镇政厅"],
    "工坊": ["市场", "面包店"],
    "码头": ["公园", "住宅区", "餐厅", "心动营地"],
    "心动营地": ["公园", "码头"],
}

# Region centers on the XZ ground plane (Y-up). Frontend NavMesh may nudge NPCs locally;
# these anchors are the authoritative sync points for SSE + tick snapshots.
# World grass footprint ≈ 120×96 m; anchors are spread so zones do not crowd old gaps.
REGION_POSITIONS: dict[str, Vec3] = {
    "广场": Vec3(x=0, y=0, z=0),
    "市场": Vec3(x=36, y=0, z=0),
    "餐厅": Vec3(x=52, y=0, z=20),
    "面包店": Vec3(x=36, y=0, z=-22),
    "公园": Vec3(x=-32, y=0, z=12),
    "住宅区": Vec3(x=18, y=0, z=38),
    "镇政厅": Vec3(x=-22, y=0, z=-20),
    "图书馆": Vec3(x=-40, y=0, z=-8),
    "工坊": Vec3(x=48, y=0, z=-36),
    "码头": Vec3(x=-8, y=0, z=40),
    # Outer fringe NW of 公园/码头; ≥12 wire units from existing anchors.
    "心动营地": Vec3(x=-56, y=0, z=36),
}


def position_for_location(location: str) -> Vec3:
    return REGION_POSITIONS.get(location, Vec3()).model_copy()
