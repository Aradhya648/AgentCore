"""Minimal town world state for spike harness (no DB, no SSE contract)."""

from __future__ import annotations

from dataclasses import dataclass, field

LOCATIONS = (
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
)

LOCATION_NEIGHBORS: dict[str, list[str]] = {
    "广场": ["市场", "公园", "镇政厅", "图书馆"],
    "市场": ["广场", "面包店", "餐厅", "工坊"],
    "餐厅": ["市场", "住宅区", "码头"],
    "面包店": ["市场", "住宅区", "工坊"],
    "公园": ["广场", "住宅区", "码头", "图书馆"],
    "住宅区": ["餐厅", "面包店", "公园", "码头"],
    "镇政厅": ["广场", "图书馆"],
    "图书馆": ["广场", "公园", "镇政厅"],
    "工坊": ["市场", "面包店"],
    "码头": ["公园", "住宅区", "餐厅"],
}


@dataclass
class AgentState:
    agent_id: str
    name: str
    role: str
    location: str = "广场"
    activity: str = "闲逛"
    mood: float = 0.0
    goal: str = ""
    last_thought: str = ""


@dataclass
class WorldState:
    tick: int = 0
    hour: int = 8
    agents: dict[str, AgentState] = field(default_factory=dict)
    event_log: list[str] = field(default_factory=list)

    def advance_clock(self) -> None:
        self.tick += 1
        self.hour = (8 + self.tick) % 24

    def agents_at(self, location: str, *, exclude: str | None = None) -> list[AgentState]:
        return [
            a
            for a in self.agents.values()
            if a.location == location and a.agent_id != exclude
        ]

    def perceive(self, agent_id: str) -> str:
        agent = self.agents[agent_id]
        here = self.agents_at(agent.location, exclude=agent_id)
        nearby = LOCATION_NEIGHBORS.get(agent.location, [])
        others_summary = (
            ", ".join(f"{a.name}({a.activity})" for a in here) if here else "无"
        )
        recent = self.event_log[-5:] if self.event_log else ["（尚无公共事件）"]
        return (
            f"【小镇感知 · tick {self.tick} · {self.hour:02d}:00】\n"
            f"你在：{agent.location}\n"
            f"当前活动：{agent.activity}\n"
            f"心情：{agent.mood:+.1f}\n"
            f"个人目标：{agent.goal}\n"
            f"同处此地：{others_summary}\n"
            f"可前往：{', '.join(nearby)}\n"
            f"近期镇事：{'；'.join(recent)}"
        )

    def record(self, line: str) -> None:
        self.event_log.append(line)
