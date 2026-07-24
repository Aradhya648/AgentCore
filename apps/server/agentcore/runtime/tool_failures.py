"""Run-scoped tool failure facts for honest finalize / CEO synthesis.

Aggregated on :class:`~agentcore.runtime.loop_controller.LoopController` (same
counters as the circuit breaker). This module only formats and injects — it does
not own a parallel tally.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agentcore.llm.provider.protocol import LLMMessage

# Marker block upserted into the system message for worker/CEO wrap-up.
_CONSTRAINT_OPEN = "<tool_failure_hard_constraint>"
_CONSTRAINT_CLOSE = "</tool_failure_hard_constraint>"

_LAST_ERROR_CAP = 200


@dataclass(frozen=True)
class ToolFailureFact:
    """One tool's failure summary for a single run."""

    tool_name: str
    failure_count: int
    last_error: str
    succeeded_after: bool

    @property
    def outstanding(self) -> bool:
        """True when failures were not cancelled by a later success of the same tool."""
        return self.failure_count > 0 and not self.succeeded_after

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "failure_count": self.failure_count,
            "last_error": self.last_error,
            "succeeded_after": self.succeeded_after,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ToolFailureFact | None:
        name = str(data.get("tool_name") or "").strip()
        if not name:
            return None
        try:
            count = int(data.get("failure_count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            return None
        return cls(
            tool_name=name,
            failure_count=count,
            last_error=cap_error_summary(str(data.get("last_error") or "")),
            succeeded_after=bool(data.get("succeeded_after")),
        )


def cap_error_summary(text: str, *, limit: int = _LAST_ERROR_CAP) -> str:
    """Collapse whitespace and truncate for prompt / tool-result surfaces."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)] + "…"


def facts_from_dicts(rows: Sequence[Mapping[str, Any]] | None) -> list[ToolFailureFact]:
    out: list[ToolFailureFact] = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        fact = ToolFailureFact.from_dict(row)
        if fact is not None:
            out.append(fact)
    return out


def outstanding_facts(facts: Sequence[ToolFailureFact]) -> list[ToolFailureFact]:
    return [f for f in facts if f.outstanding]


def format_tool_failures_section(
    facts: Sequence[ToolFailureFact], *, heading: str = "### tool_failures"
) -> str:
    """Structured block for delegate / synthesis consumers. Empty when no failures."""
    if not facts:
        return ""
    lines = [
        heading,
        "以下为引擎按 run 聚合的工具失败事实（地面真相）。"
        "``succeeded_after=true`` 表示同工具后来已成功，不必当缺口播报；"
        "``succeeded_after=false`` 表示仍有未抵消失败，终稿必须如实写出。",
    ]
    for fact in facts:
        err = fact.last_error or "（无摘要）"
        lines.append(
            f"- `{fact.tool_name}`：failures={fact.failure_count}，"
            f"succeeded_after={'true' if fact.succeeded_after else 'false'}，"
            f"last_error={err}"
        )
    return "\n".join(lines)


def format_hard_constraint(outstanding: Sequence[ToolFailureFact]) -> str:
    """One-line hard constraint for system prompt / wrap-up steers."""
    names = "、".join(f"`{f.tool_name}`" for f in outstanding)
    return (
        "【工具失败硬约束】本回合以下操作未能成功（未被同工具后续成功抵消）："
        f"{names}。"
        "必须如实告知哪些步骤没做成；禁止宣称已完成未执行成功的步骤。"
        "重试后已成功的工具不算缺口、无需当失败播报。"
    )


def sync_tool_failure_constraint_in_system(
    messages: list[LLMMessage],
    outstanding: Sequence[ToolFailureFact],
    *,
    constraint_text: str | None = None,
) -> bool:
    """Upsert or clear the hard-constraint block on the first system message.

    Returns True when ``messages`` was mutated. Pass ``constraint_text`` to inject
    a pre-formatted line (e.g. team-level) instead of formatting ``outstanding``.
    """
    if not messages or messages[0].role != "system":
        return False
    body = messages[0].content or ""
    stripped = _strip_constraint_block(body)
    text = (constraint_text or "").strip()
    if not text and outstanding:
        text = format_hard_constraint(outstanding)
    if not text:
        if stripped == body:
            return False
        messages[0] = LLMMessage(role="system", content=stripped)
        return True
    block = f"\n\n{_CONSTRAINT_OPEN}\n{text}\n{_CONSTRAINT_CLOSE}"
    new_body = stripped + block
    if new_body == body:
        return False
    messages[0] = LLMMessage(role="system", content=new_body)
    return True


def team_outstanding_constraint_from_messages(messages: Sequence[LLMMessage]) -> str | None:
    """Hard-constraint line when a delegate tool result still has uncompensated failures."""
    for msg in messages:
        if msg.role != "tool":
            continue
        content = msg.content or ""
        if "### tool_failures" not in content:
            continue
        # Match fact lines only (``succeeded_after=false``), not prose that mentions the token.
        if "succeeded_after=false，" not in content and "succeeded_after=false," not in content:
            continue
        return (
            "【工具失败硬约束】团队委派结果中仍有未被同工具后续成功抵消的工具失败"
            "（见工具结果 ``tool_failures`` 段）。"
            "终稿必须如实告知哪些操作没成功；禁止宣称已完成未执行成功的步骤。"
            "重试后已成功的工具不算缺口、无需当失败播报。"
        )
    return None


def _strip_constraint_block(body: str) -> str:
    start = body.find(_CONSTRAINT_OPEN)
    if start < 0:
        return body
    end = body.find(_CONSTRAINT_CLOSE, start)
    if end < 0:
        return body[:start].rstrip()
    end += len(_CONSTRAINT_CLOSE)
    return (body[:start] + body[end:]).rstrip()


def format_team_tool_failures_block(
    products: Sequence[Mapping[str, Any]],
) -> str:
    """CEO-facing multi-worker ``tool_failures`` section, or "" when none."""
    chunks: list[str] = []
    any_outstanding = False
    for wp in products:
        rows = wp.get("tool_failures")
        facts = facts_from_dicts(rows if isinstance(rows, list) else None)
        if not facts:
            continue
        role = str(wp.get("role") or "worker")
        run_id = str(wp.get("run_id") or "")
        head = f"#### {role}"
        if run_id:
            head += f" · run_id: `{run_id}`"
        section = format_tool_failures_section(facts, heading=head)
        if section:
            chunks.append(section)
        if outstanding_facts(facts):
            any_outstanding = True
    if not chunks:
        return ""
    body = (
        "\n### tool_failures\n"
        "各队员 run 内工具失败聚合（引擎地面真相，非模型自评）。"
        "终稿必须对照；有 ``succeeded_after=false`` 时不得写成全员操作成功。\n\n"
        + "\n\n".join(chunks)
    )
    if any_outstanding:
        outstanding_names: list[str] = []
        for wp in products:
            facts = facts_from_dicts(
                wp.get("tool_failures") if isinstance(wp.get("tool_failures"), list) else None
            )
            for fact in outstanding_facts(facts):
                label = str(wp.get("role") or wp.get("run_id") or "worker")
                outstanding_names.append(f"`{label}`/`{fact.tool_name}`")
        joined = "、".join(outstanding_names)
        body += (
            "\n\n【工具失败硬约束】团队中以下操作未能成功（未被同工具后续成功抵消）："
            f"{joined}。"
            "终稿必须如实告知用户哪些步骤没做成；禁止宣称已完成未执行成功的步骤。"
            "重试后已成功的工具不算缺口、无需当失败播报。"
        )
    return body
