"""Built-in tool implementations — registries collect from ``tools.registration``."""

from typing import Literal

from agentcore.config import settings
from agentcore.core.types import PermissionAxes, ToolApproval, ToolCategory
from agentcore.tools.registration import (
    AUDIENCE_CEO,
    ToolSurface,
    declared_tool_name,
    declared_tools,
    execution_class_tool_names,
    instantiate_declared,
    tool_registration,
)
from agentcore.tools.registry import ToolRegistry
from agentcore.workspace.protocol import WorkspaceBackend


def code_execution_enabled_for(backend: WorkspaceBackend | None) -> bool:
    """Whether the code-execution tool class may appear in a runtime worker toolset.

    Governs the WHOLE class that runs code through the sandbox chain — ``code_execute``
    AND ``test_run`` (a test suite executes arbitrary project code, so it is
    execution-equivalent). Local / sidecar execution stays on; cloud ``location=server``
    defaults off unless ``GVISOR_ENABLED`` or ``CODE_EXECUTE_CLOUD_ENABLED`` is set (a
    plain subprocess in the API container is not a real isolation boundary — 安全权限与
    治理 §5). Keeping both tools behind ONE predicate (not a per-tool special-case) is
    what makes the production-security posture cover the class consistently.

    When cloud execution is config-enabled, a boot-time sandbox ``health_check`` result
    (``tools.sandbox.cloud_health``) also gates this predicate: a failed probe withholds
    the class so registry registration and ``workspace_context`` stay truthful. An
    unprobed process (tests, lifespan not run, config off) keeps config-only semantics.
    """
    if backend is None:
        return True
    if backend.location == "local":
        return True
    if not (settings.gvisor_enabled or settings.code_execute_cloud_enabled):
        return False
    from agentcore.tools.sandbox.cloud_health import cloud_sandbox_health

    # False → known unhealthy; True / None (never probed) → config gate alone.
    return cloud_sandbox_health() is not False


def browser_execution_enabled_for(backend: WorkspaceBackend | None) -> bool:
    """Whether the L3 team-browser tool class may appear in a worker toolset (D11 / C1).

    Two paths (never mixed on one session — C4):

    - **server + gVisor**: real isolation; folds the boot-time sandbox health probe
      and the browser netns capability probe (``network_mode=none`` does not cover
      netns). (``code_execute_cloud_enabled`` subprocess path does NOT enable browsers.)
    - **local + DesktopBrowserBridge**: desktop re-sends ``browserBridge`` on each
      sidecar turn (``apply_desktop_bridge_from_turn``); we require a successful
      ``GET /health`` for the **current** credential generation. Unconfigured /
      unhealthy → withhold tools (no silent sandbox fallback).
    """
    if backend is None:
        return False
    if backend.location == "local":
        from agentcore.runtime.browser.desktop_bridge import (
            desktop_bridge_configured,
            desktop_bridge_health,
            ensure_desktop_bridge_health,
        )

        # Cached True → allow; False → withhold; None → probe once if env present.
        cached = desktop_bridge_health()
        if cached is True:
            return True
        if cached is False:
            return False
        if not desktop_bridge_configured():
            return False
        return ensure_desktop_bridge_health()
    if backend.location != "server":
        return False
    if not settings.gvisor_enabled:
        return False
    from agentcore.tools.sandbox.cloud_health import cloud_sandbox_health

    # False → known unhealthy; True / None (never probed) → config + cloud gate alone.
    if cloud_sandbox_health() is False:
        return False
    # Netns is orthogonal to GVisorSandbox.health_check (network_mode=none): a failed
    # boot / sticky probe withholds browser_* so the model never first-fails then trips
    # the circuit. None (tests / unbooted) keeps status quo — do not withhold.
    from agentcore.tools.sandbox.browser.netns import browser_netns_health

    return browser_netns_health() is not False


def build_builtin_registry(
    *,
    include_execution_tools: bool = True,
    include_host_tools: bool = False,
    include_browser: bool = False,
    location: Literal["server", "local"] | None = None,
    languages: tuple[str, ...] | list[str] | None = None,
) -> ToolRegistry:
    """Register the platform's built-in tools (single source: ``DECLARED_TOOLS``).

    Both the chat pipeline (worker toolset) and the read-only capability catalog
    build from declarations with ``surface=builtin``. CEO orchestration primitives
    and worker-only tools are separate surfaces.

    ``include_execution_tools`` gates the code-execution class as a unit
    (``test_run`` + ``code_execute`` + local ``terminal``): the worker registry
    withholds the class on a backend that can't run code safely (see
    ``code_execution_enabled_for``). ``terminal`` is additionally ``local_only``.

    ``include_host_tools`` gates the Host face (``host_class``): only when the
    desktop backfill channel is reachable and ``host≠off``.

    ``include_browser`` gates the L3 browser class on the builtin surface
    (navigate/click/type/scroll/snapshot — CEO+worker; screenshot stays worker-only).
    Default False so a no-Bridge / no-gVisor process does not leak browser tools into the
    default builtin roster.

    ``location`` stamps ``code_execute``'s description to match the turn's backend
    and gates ``local_only`` tools (``terminal`` only when ``location=="local"``).
    ``languages`` trims ``code_execute``'s language enum after a local/sidecar probe
    (cloud / catalog leave ``None`` → full fixed surface).
    """
    registry = ToolRegistry()
    for cls in declared_tools(surface=ToolSurface.BUILTIN):
        reg = tool_registration(cls)
        if reg.execution_class and not include_execution_tools:
            continue
        if reg.host_class and not include_host_tools:
            continue
        if reg.browser_class and not include_browser:
            continue
        if reg.local_only and location != "local":
            continue
        registry.register(
            instantiate_declared(cls, location=location, languages=languages)
        )
    return registry


def build_worker_registry(
    *,
    backend: WorkspaceBackend | None = None,
    permission_axes: "PermissionAxes | None" = None,
    languages: tuple[str, ...] | list[str] | None = None,
    desktop_online: bool = False,
) -> ToolRegistry:
    """The delegated worker's toolset: builtins PLUS worker-only declarations.

    ``command=ask`` withholds the entire execution class
    (``code_execute`` / ``test_run`` / ``terminal``) — read-only retrieval stays on.
    Host tools gate on ``desktop_online`` ∧ ``host≠off`` (orthogonal to command).
    """
    location = backend.location if backend is not None else None
    include_execution = code_execution_enabled_for(backend)
    if permission_axes is not None and permission_axes.withholds_execution_tools:
        include_execution = False
    include_browser = include_execution and browser_execution_enabled_for(backend)
    include_host = desktop_online and (
        permission_axes is None or not permission_axes.host_disabled
    )
    # Prefer explicit languages; else reuse a probe cached on the backend by
    # ``resolve_exec_languages`` (prepare / resume). Cloud stays untrimmed.
    resolved_languages = languages
    if resolved_languages is None and backend is not None:
        resolved_languages = getattr(backend, "_exec_languages", None)
    if location != "local":
        resolved_languages = None
    registry = build_builtin_registry(
        include_execution_tools=include_execution,
        include_host_tools=include_host,
        include_browser=include_browser,
        location=location,
        languages=resolved_languages,
    )
    for cls in declared_tools(surface=ToolSurface.WORKER_ONLY):
        reg = tool_registration(cls)
        if reg.manual_wire:
            # Privacy-gated (e.g. conversation log tools): wired after registry build
            # when the user gate is on — see ``_wire_worker_conversation_log_tools``.
            continue
        if reg.execution_class and not include_execution:
            continue
        if reg.browser_class and not include_browser:
            continue
        if reg.host_class and not include_host:
            continue
        if reg.local_only and (backend is None or backend.location != "local"):
            continue
        registry.register(instantiate_declared(cls, location=location))
    return registry


def build_ceo_tool_registry(
    *,
    desktop_online: bool = False,
    permission_axes: "PermissionAxes | None" = None,
    backend_location: str | None = None,
    include_browser: bool = False,
) -> ToolRegistry:
    """The CEO chat agent's DIRECT toolset: read / retrieval + Host + local terminal.

    Collects ``surface=builtin`` tools whose declared audience includes ``ceo``.
    Historically aligned with ``approval=NEVER``; **P3 exception**: ``host_shell``
    is GRANTABLE and CEO-holdable (Host face only — L2/L3 stay worker-only).
    **B2**: local ``terminal`` is also CEO-holdable (schema NEVER; ``start`` elevates
    at runtime like ``git`` write) for pure start/stop/list of workspace long-running
    processes — not a GRANTABLE schema exception.
    **Browser**: navigate/click/type/scroll/snapshot (GRANTABLE · ``browser_class``),
    gated by ``include_browser`` — same tier as host_shell / terminal; screenshot
    stays worker-only (visual验收).
    Orchestration primitives are wired separately in ``_assemble_ceo_toolset``.
    Host tools appear only when ``desktop_online`` ∧ ``host≠off``.
    ``terminal`` appears only when ``backend_location=="local"``.
    """
    include_host = desktop_online and (
        permission_axes is None or not permission_axes.host_disabled
    )
    location: Literal["server", "local"] | None = (
        "local" if backend_location == "local" else None
    )
    full = build_builtin_registry(
        include_host_tools=include_host,
        include_browser=include_browser,
        location=location,
    )
    registry = ToolRegistry()
    ceo_names = {
        declared_tool_name(cls)
        for cls in declared_tools(surface=ToolSurface.BUILTIN)
        if AUDIENCE_CEO in tool_registration(cls).audience
    }
    for schema in full.list_all():
        if schema.name in ceo_names:
            registry.register(full.get(schema.name))
    return registry


def approval_class_tool_names() -> frozenset[str]:
    """Tools covered by an ``APPROVE_ALWAYS_FILES`` turn grant.

    The file-mutation class plus ``git`` write (``git`` schema stays ``NEVER`` so
    CEO read-only subcommands stay in the filtered registry).
    """
    return file_mutation_tool_names() | frozenset({"git"})


def file_mutation_tool_names() -> frozenset[str]:
    """The GRANTABLE file-mutation tools as one class — what a
    「本轮内允许所有文件改动」grant covers.

    Derived from the single builtin registry as ``GRANTABLE ∩ FILESYSTEM``.
    """
    full = build_builtin_registry()
    return frozenset(
        schema.name
        for schema in full.list_all()
        if schema.approval is ToolApproval.GRANTABLE and schema.category is ToolCategory.FILESYSTEM
    )


def file_only_tool_names() -> frozenset[str]:
    """Tools an organize worker may hold: filesystem read + mutation (no execute/terminal)."""
    full = build_builtin_registry()
    names = {
        schema.name
        for schema in full.list_all()
        if schema.category is ToolCategory.FILESYSTEM
    }
    # Grep is FILESYSTEM-adjacent but often categorized separately — include if present.
    for extra in ("grep", "code_search"):
        if full.get(extra) is not None:
            names.add(extra)
    return frozenset(names)


def delegation_grantable_tool_names() -> frozenset[str]:
    """Tools covered by a kickoff / per-delegation grant (统一授权白名单).

    File-mutation class + ``git`` writes + every declared ``execution_class`` tool.
    """
    return approval_class_tool_names() | execution_class_tool_names()


def per_call_tool_names() -> frozenset[str]:
    """Tools whose「本轮内都允许」is refused and downgraded to a one-shot approve.

    Empty by design (Cursor-aligned UX, 2026-07).
    """
    return frozenset()
