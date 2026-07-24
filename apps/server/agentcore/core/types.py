"""Shared enumerations and base types used across all modules."""

from enum import StrEnum
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
    via AutonomyPolicy). The former ``ALWAYS`` (every call, no turn grant) had no
    consumers and was removed — irreversible external tools are not in the MVP set.
    """

    NEVER = "never"
    GRANTABLE = "grantable"


class AutonomyPolicy(StrEnum):
    """User-global *default* for new conversations (maps to :class:`PermissionPreset`).

    Runtime gates no longer read this directly — the conversation's
    ``permission_preset`` is the single source of truth. This enum remains the
    stored shape of ``users.autonomy_policy`` (设置页「新会话默认权限模式」).

    Mapping: ``always_ask``→observe, ``first_grant``→workspace, ``full_auto``→full_trust.
    """

    ALWAYS_ASK = "always_ask"
    FIRST_GRANT = "first_grant"
    FULL_AUTO = "full_auto"


class PermissionPreset(StrEnum):
    """Conversation-level permission mode (会话级权限模式 · 运行时单一真相源).

    - ``observe`` — no execution tools; GRANTABLE (writes) always prompt; kickoff
      does not pre-authorize write capabilities (≈ always_ask + withhold execution)
    - ``workspace`` — kickoff once authorizes grantable set (≈ first_grant; default)
    - ``full_trust`` — skip kickoff; silent auto-grant including local execution
      (≈ full_auto; UI must warn that AI runs commands with user-equivalent power)
    """

    OBSERVE = "observe"
    WORKSPACE = "workspace"
    FULL_TRUST = "full_trust"


_AUTONOMY_TO_PRESET: dict[AutonomyPolicy, PermissionPreset] = {
    AutonomyPolicy.ALWAYS_ASK: PermissionPreset.OBSERVE,
    AutonomyPolicy.FIRST_GRANT: PermissionPreset.WORKSPACE,
    AutonomyPolicy.FULL_AUTO: PermissionPreset.FULL_TRUST,
}

_PRESET_TO_AUTONOMY: dict[PermissionPreset, AutonomyPolicy] = {
    PermissionPreset.OBSERVE: AutonomyPolicy.ALWAYS_ASK,
    PermissionPreset.WORKSPACE: AutonomyPolicy.FIRST_GRANT,
    PermissionPreset.FULL_TRUST: AutonomyPolicy.FULL_AUTO,
}


def autonomy_to_preset(policy: AutonomyPolicy) -> PermissionPreset:
    """Map user-default AutonomyPolicy → conversation PermissionPreset."""
    return _AUTONOMY_TO_PRESET.get(policy, PermissionPreset.WORKSPACE)


def preset_to_autonomy(preset: PermissionPreset) -> AutonomyPolicy:
    """Map conversation PermissionPreset → AutonomyPolicy for kickoff / ApprovalGate."""
    return _PRESET_TO_AUTONOMY.get(preset, AutonomyPolicy.FIRST_GRANT)


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
