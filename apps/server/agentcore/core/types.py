"""Shared enumerations and base types used across all modules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


# --- Core Enumerations ---


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolApproval(StrEnum):
    """Tool approval requirement levels (可逆性 × 副作用).

    Two live levels: ``NEVER`` (silent) and ``GRANTABLE`` (first-grant / per-call
    via session permission axes). The former ``ALWAYS`` (every call, no turn grant)
    had no consumers and was removed — irreversible external tools are not in the
    MVP set.
    """

    NEVER = "never"
    GRANTABLE = "grantable"


class FileWriteAxis(StrEnum):
    """Whether reversible file mutations need per-call approval."""

    ASK = "ask"
    SESSION = "session"


class CommandAxis(StrEnum):
    """How execution-class tools (code / terminal / test) are authorized."""

    ASK = "ask"
    KICKOFF = "kickoff"
    AUTO = "auto"


class TeamKickoffAxis(StrEnum):
    """Whether / when the team kickoff card (plan + capability halves) hangs."""

    ALWAYS = "always"
    RULES = "rules"
    SKIP = "skip"


class HostAxis(StrEnum):
    """本机 Host 面授权（与 ``command`` 正交；不挂 execution_class / 不吃 kickoff 静默授）。"""

    OFF = "off"
    ASK = "ask"
    SESSION = "session"


class AutonomyPolicy(StrEnum):
    """User-global *default recipe* for new conversations (seeds :class:`PermissionAxes`).

    Runtime gates read the conversation's ``permission_axes`` — not this column.
    Stored on ``users.autonomy_policy`` (设置页「新会话默认权限配方」).
    """

    CAUTIOUS = "cautious"  # ask / ask / rules / off
    LESS_INTERRUPT = "less_interrupt"  # session / auto / rules / ask (default)
    MANAGED = "managed"  # session / auto / skip / session


@dataclass(frozen=True)
class PermissionAxes:
    """Conversation-level permission axes (运行时单一真相源).

    - ``file_write`` — ask = per-call; session = trust reversible writes
    - ``command`` — ask = withhold/no kickoff grant; kickoff = card authorizes;
      auto = silent local exec
    - ``team_kickoff`` — always / rules / skip for the team card
    - ``host`` — off / ask / session for the local Host face (orthogonal to command)

    Illegal: ``command=auto`` ∧ ``file_write=ask``.
    ask_user / plan_review / circuit-breakers / sensitive reads are orthogonal.
    """

    file_write: FileWriteAxis = FileWriteAxis.SESSION
    command: CommandAxis = CommandAxis.AUTO
    team_kickoff: TeamKickoffAxis = TeamKickoffAxis.RULES
    host: HostAxis = HostAxis.ASK

    def __post_init__(self) -> None:
        if self.command is CommandAxis.AUTO and self.file_write is FileWriteAxis.ASK:
            raise ValueError(
                "illegal permission axes: command=auto requires file_write=session"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "file_write": self.file_write.value,
            "command": self.command.value,
            "team_kickoff": self.team_kickoff.value,
            "host": self.host.value,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> PermissionAxes:
        """Parse stored / wire JSON; unknown / missing → less_interrupt defaults.

        Explicitly resolves ``host`` (缺省 = 默认 ``ask``); never silently drop it.
        """
        if not raw:
            return DEFAULT_PERMISSION_AXES
        try:
            return cls(
                file_write=FileWriteAxis(
                    str(raw.get("file_write") or FileWriteAxis.SESSION.value)
                ),
                command=CommandAxis(str(raw.get("command") or CommandAxis.AUTO.value)),
                team_kickoff=TeamKickoffAxis(
                    str(raw.get("team_kickoff") or TeamKickoffAxis.RULES.value)
                ),
                host=HostAxis(str(raw.get("host") or HostAxis.ASK.value)),
            )
        except (ValueError, TypeError, KeyError):
            return DEFAULT_PERMISSION_AXES

    @property
    def trusts_file_writes(self) -> bool:
        return self.file_write is FileWriteAxis.SESSION

    @property
    def honors_kickoff_grant(self) -> bool:
        """True when a kickoff continue may silence execution-class tools."""
        return self.command is CommandAxis.KICKOFF

    @property
    def auto_executes(self) -> bool:
        return self.command is CommandAxis.AUTO

    @property
    def withholds_execution_tools(self) -> bool:
        """command=ask: do not register execution class (对齐原 observe 执行侧)."""
        return self.command is CommandAxis.ASK

    @property
    def skips_team_kickoff(self) -> bool:
        return self.team_kickoff is TeamKickoffAxis.SKIP

    @property
    def forces_team_kickoff(self) -> bool:
        return self.team_kickoff is TeamKickoffAxis.ALWAYS

    @property
    def host_disabled(self) -> bool:
        return self.host is HostAxis.OFF

    @property
    def trusts_host(self) -> bool:
        return self.host is HostAxis.SESSION

    @property
    def implies_deep_research_auto(self) -> bool:
        """command=auto ∧ team_kickoff=skip（托管）蕴含深度研究自治.

        少打断为 auto∧rules：仍弹组队/开辩卡，不蕴含自治跳卡。
        """
        return (
            self.command is CommandAxis.AUTO
            and self.team_kickoff is TeamKickoffAxis.SKIP
        )


DEFAULT_PERMISSION_AXES = PermissionAxes(
    file_write=FileWriteAxis.SESSION,
    command=CommandAxis.AUTO,
    team_kickoff=TeamKickoffAxis.RULES,
    host=HostAxis.ASK,
)

_RECIPE_TO_AXES: dict[AutonomyPolicy, PermissionAxes] = {
    AutonomyPolicy.CAUTIOUS: PermissionAxes(
        FileWriteAxis.ASK,
        CommandAxis.ASK,
        TeamKickoffAxis.RULES,
        HostAxis.OFF,
    ),
    AutonomyPolicy.LESS_INTERRUPT: DEFAULT_PERMISSION_AXES,
    AutonomyPolicy.MANAGED: PermissionAxes(
        FileWriteAxis.SESSION,
        CommandAxis.AUTO,
        TeamKickoffAxis.SKIP,
        HostAxis.SESSION,
    ),
}


def recipe_to_axes(policy: AutonomyPolicy) -> PermissionAxes:
    """Map user-default recipe → conversation PermissionAxes."""
    return _RECIPE_TO_AXES.get(policy, DEFAULT_PERMISSION_AXES)


def validate_permission_axes(
    *,
    file_write: str,
    command: str,
    team_kickoff: str,
    host: str = HostAxis.ASK.value,
) -> PermissionAxes:
    """Parse + validate axes for API writes; raises ValueError on illegal combo / enum."""
    return PermissionAxes(
        file_write=FileWriteAxis(file_write),
        command=CommandAxis(command),
        team_kickoff=TeamKickoffAxis(team_kickoff),
        host=HostAxis(host),
    )


class ToolCategory(StrEnum):
    FILESYSTEM = "filesystem"
    SEARCH = "search"
    EXECUTION = "execution"
    RESEARCH = "research"
    ORCHESTRATION = "orchestration"
    # A tool that pauses the turn to ask the user (the CEO ``ask_user`` checkpoint).
    # Category is declarative metadata for classification/tooling; the engine no
    # longer branches on tool category (it acts on the ToolResult, not the name).
    INTERACTION = "interaction"
    # Currently UNUSED: ``consult_skill`` was recategorised to ORCHESTRATION (it is a CEO
    # orchestration primitive, and 技能 are Prompt injection shown in the「AI 提示词」
    # catalog — not a tool group). Kept as declarative metadata so the contract type is
    # stable; removable via ``pnpm gen:types`` once we're sure no future skill-category
    # tool wants it. Like every category, the engine never branches on it.
    SKILL = "skill"


class ToolEffect(StrEnum):
    """How a tool result steers the ReAct loop.

    The engine acts on THIS effect — never on a tool's name or category (引擎纯化,
    设计 §8.5). The default ``CONTINUE`` feeds the tool output back and loops; a
    terminal effect ends the turn in-band, surfacing the result's ``final_text``
    instead of letting the model generate a second, duplicate reply.
    """

    # Default: feed the tool output back to the model and keep looping.
    CONTINUE = "continue"
    # The tool already produced AND streamed the turn's final user-facing answer
    # itself, so the loop must stop. Reserved: no current built-in sets it (the
    # legacy answer-streaming handoff was retired) — kept as the effect a future
    # streaming-handoff tool would declare.
    HANDOFF = "handoff"
    # The tool drove a user interaction that ended the turn, and its text is the
    # final answer: the CEO ``ask_user`` checkpoint on a "stop" decision (its closing
    # note is the reply). A "submit" answer instead resumes the loop (CONTINUE), so
    # only stop is terminal here.
    INTERACT = "interact"
    # 挂起即收口 (②): the tool hit a durable checkpoint and persisted a resume frame, so
    # the loop must END the turn awaiting ``POST .../resume`` — NOT because an answer was
    # produced. Unlike INTERACT/HANDOFF it carries NO ``final_text`` (there is no reply
    # yet) and the suspended tool_call is left PENDING (no tool result recorded), so the
    # resumed window ends exactly at the assistant. The engine maps it to
    # FinishReason.PAUSED. Returned by any durable checkpoint whose frame was persisted
    # (D11: un-persistable runtime failure terminates the turn — no in-memory wait).
    SUSPEND = "suspend"
