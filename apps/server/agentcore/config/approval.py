"""Tool approval gate settings."""

from pydantic import BaseModel, Field


class ApprovalSettings(BaseModel):
    approval_gate_enabled: bool = True
    # 提问确认交互统一 D2：默认无限等（None）；运维可设上限。timeout 逻辑保留。
    approval_timeout_seconds: float | None = None
    # Per-tool approval wait ceilings; unset tools fall back to approval_timeout_seconds.
    # 默认清空（不再对 file_write 设 900s）；运维可配置。
    approval_timeout_overrides: dict[str, float] = Field(default_factory=dict)

    def approval_timeout_for(self, tool_name: str) -> float | None:
        if tool_name in self.approval_timeout_overrides:
            return self.approval_timeout_overrides[tool_name]
        return self.approval_timeout_seconds
