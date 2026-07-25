"""Declarative tool registration — class metadata + single roster.

Mirrors the LLM vendor chain (prefix table + settings ⇒ access): a new built-in
tool is **implement class (with ``registration``) + append to ``DECLARED_TOOLS``
+ test**. Runtime registries, the capability catalog, and board wiring **collect**
from declarations instead of maintaining parallel hand lists.

CEO orchestration tools with heavy ``__init__`` deps are still constructed in
``_assemble_ceo_toolset`` / coordination surface, but **which** tools exist and
their audience / wire gate come from ``ToolRegistration`` — not a second tuple
in ``catalog.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from agentcore.tools.protocol import ToolSchema

if TYPE_CHECKING:
    from agentcore.tools.registry import ToolRegistry

# Audience tokens — same strings as ``tools.catalog.AVAILABLE_TO_*``.
AUDIENCE_CEO = "ceo"
AUDIENCE_WORKER = "worker"
AUDIENCE_CEO_ONLY: tuple[str, ...] = (AUDIENCE_CEO,)
AUDIENCE_WORKER_ONLY: tuple[str, ...] = (AUDIENCE_WORKER,)
AUDIENCE_BOTH: tuple[str, ...] = (AUDIENCE_CEO, AUDIENCE_WORKER)


class ToolSurface(StrEnum):
    """Where a tool class is collected into a runtime registry / catalog section."""

    BUILTIN = "builtin"
    WORKER_ONLY = "worker_only"
    CEO_ORCHESTRATION = "ceo_orchestration"


class CeoWire(StrEnum):
    """When a CEO-orchestration tool is wired at runtime (catalog always lists it)."""

    ALWAYS = "always"
    MEMORY = "memory"
    CHECKPOINT = "checkpoint"
    BOARD = "board"
    # Advertised in catalog; runtime inject via ``ceo_surface`` (idle/coord gate).
    COORDINATION = "coordination"


@dataclass(frozen=True)
class ToolRegistration:
    """Class-level registration metadata collected by registries / catalog / wire."""

    surface: ToolSurface
    audience: tuple[str, ...]
    execution_class: bool = False
    local_only: bool = False
    ceo_wire: CeoWire = CeoWire.ALWAYS
    # ``code_execute`` stamps description from backend location.
    needs_location: bool = False
    # L3 team browser (D11): cloud-only + needs a real gVisor isolation boundary
    # (a browser can't run in a plain subprocess). Gated by ``browser_execution_enabled_for``
    # ON TOP OF ``execution_class`` (observe withholds the class; gVisor cloud enables it).
    browser_class: bool = False


def tool_registration(cls: type) -> ToolRegistration:
    reg = getattr(cls, "registration", None)
    if not isinstance(reg, ToolRegistration):
        raise TypeError(f"{cls.__name__} must declare class attribute ``registration``")
    return reg


def read_static_schema(tool_cls: type) -> ToolSchema:
    """Read a pure-static ``schema`` without running heavy ``__init__``."""
    instance = object.__new__(tool_cls)
    return instance.schema  # type: ignore[attr-defined]


def declared_tool_name(cls: type) -> str:
    reg = tool_registration(cls)
    if reg.needs_location:
        return cls(location=None).schema.name  # type: ignore[call-arg]
    if reg.surface is ToolSurface.CEO_ORCHESTRATION:
        return read_static_schema(cls).name
    return cls().schema.name  # type: ignore[call-arg]


def instantiate_declared(
    cls: type,
    *,
    location: Literal["server", "local"] | None = None,
) -> Any:
    """Zero-arg (or location-aware) construction for builtin / worker-only / board tools."""
    reg = tool_registration(cls)
    if reg.needs_location:
        return cls(location=location)  # type: ignore[call-arg]
    return cls()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Single roster (append here when adding a tool class)
# ---------------------------------------------------------------------------

def _load_declared_tools() -> tuple[type, ...]:
    """Import tool classes and return the ordered declaration roster.

    Order is part of the public surface (registry / catalog / OpenAI defs).
    """
    from agentcore.tools.builtin.amend_note import AmendNoteTool
    from agentcore.tools.builtin.ask_user import AskUserTool
    from agentcore.tools.builtin.board_ops import BoardOpsTool
    from agentcore.tools.builtin.board_read import BoardReadTool
    from agentcore.tools.builtin.browser import (
        BrowserClickTool,
        BrowserNavigateTool,
        BrowserScreenshotTool,
        BrowserScrollTool,
        BrowserSnapshotTool,
        BrowserTypeTool,
    )
    from agentcore.tools.builtin.code_execute import CodeExecuteTool
    from agentcore.tools.builtin.code_search import CodeSearchTool
    from agentcore.tools.builtin.consult_memory import ConsultMemoryTool
    from agentcore.tools.builtin.consult_skill import ConsultSkillTool
    from agentcore.tools.builtin.debate import DebateTool
    from agentcore.tools.builtin.delegate import DelegateTool
    from agentcore.tools.builtin.desktop_notify import DesktopNotifyTool
    from agentcore.tools.builtin.escalate import EscalateTool
    from agentcore.tools.builtin.file_ops import (
        FileAppendTool,
        FileBatchTool,
        FileCopyTool,
        FileDeleteTool,
        FileListTool,
        FileMoveTool,
        FileReadTool,
        FileWriteTool,
        MkdirTool,
        StrReplaceTool,
        WriteSectionTool,
    )
    from agentcore.tools.builtin.git_ops import GitTool
    from agentcore.tools.builtin.grep import GrepTool
    from agentcore.tools.builtin.handoff import HandoffTool
    from agentcore.tools.builtin.post_note import PostNoteTool
    from agentcore.tools.builtin.read_notes import ReadNotesTool
    from agentcore.tools.builtin.remember import RememberTool
    from agentcore.tools.builtin.replan import ReplanTool
    from agentcore.tools.builtin.terminal import TerminalTool
    from agentcore.tools.builtin.test_run import TestRunTool
    from agentcore.tools.builtin.update_project_profile import UpdateProjectProfileTool
    from agentcore.tools.builtin.web.read_url import ReadUrlTool
    from agentcore.tools.builtin.web.search import WebSearchTool

    return (
        # builtin (platform base)
        WebSearchTool,
        ReadUrlTool,
        FileReadTool,
        FileWriteTool,
        FileAppendTool,
        StrReplaceTool,
        WriteSectionTool,
        FileListTool,
        FileDeleteTool,
        FileMoveTool,
        FileCopyTool,
        MkdirTool,
        FileBatchTool,
        GrepTool,
        CodeSearchTool,
        GitTool,
        TestRunTool,
        CodeExecuteTool,
        # worker_only
        EscalateTool,
        PostNoteTool,
        ReadNotesTool,
        AmendNoteTool,
        HandoffTool,
        DesktopNotifyTool,
        TerminalTool,
        # L3 团队浏览器 (D11): worker-only, cloud-only gVisor, execution_class + GRANTABLE
        BrowserNavigateTool,
        BrowserClickTool,
        BrowserTypeTool,
        BrowserScrollTool,
        BrowserSnapshotTool,
        BrowserScreenshotTool,
        # ceo_orchestration (catalog order)
        DelegateTool,
        ReplanTool,
        DebateTool,
        ConsultSkillTool,
        ConsultMemoryTool,
        RememberTool,
        UpdateProjectProfileTool,
        AskUserTool,
        BoardOpsTool,
        BoardReadTool,
    )


# Lazy so importing ``registration`` from a tool module during class body does not
# recurse through every tool import. Populated on first ``declared_tools()`` call.
_DECLARED_TOOLS: tuple[type, ...] | None = None


def declared_tools(*, surface: ToolSurface | None = None) -> tuple[type, ...]:
    global _DECLARED_TOOLS
    if _DECLARED_TOOLS is None:
        _DECLARED_TOOLS = _load_declared_tools()
    if surface is None:
        return _DECLARED_TOOLS
    return tuple(cls for cls in _DECLARED_TOOLS if tool_registration(cls).surface is surface)


def execution_class_tool_names() -> frozenset[str]:
    """Tools flagged ``execution_class`` (code_execute / test_run / terminal)."""
    return frozenset(
        declared_tool_name(cls)
        for cls in declared_tools()
        if tool_registration(cls).execution_class
    )


def declared_tool_names() -> frozenset[str]:
    """Every name on the declaration roster (any surface / audience)."""
    return frozenset(declared_tool_name(cls) for cls in declared_tools())


def worker_only_tool_names() -> frozenset[str]:
    """Tools whose audience excludes CEO (write / execute / worker orchestration)."""
    return frozenset(
        declared_tool_name(cls)
        for cls in declared_tools()
        if AUDIENCE_CEO not in tool_registration(cls).audience
    )


def register_board_ceo_tools(chat_tools: ToolRegistry) -> None:
    """Register CEO board tools (``ceo_wire=BOARD``) — shared by assemble + resume."""
    for cls in declared_tools(surface=ToolSurface.CEO_ORCHESTRATION):
        if tool_registration(cls).ceo_wire is CeoWire.BOARD:
            chat_tools.register(instantiate_declared(cls))
