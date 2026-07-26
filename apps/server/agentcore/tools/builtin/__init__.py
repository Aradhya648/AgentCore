"""Built-in tool implementations — registries collect from ``tools.registration``."""

from typing import Literal

from agentcore.config import settings
from agentcore.core.types import PermissionPreset, ToolApproval, ToolCategory
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
    """Whether the L3 team-browser tool class may appear in a worker toolset (D11).

    Cloud-only AND needs a REAL gVisor isolation boundary — a browser cannot run in a
    plain subprocess, so (unlike ``code_execution_enabled_for``) the
    ``code_execute_cloud_enabled`` subprocess path does NOT enable it. Local / sidecar
    backends do not host browser sessions in M0. Folds the same boot-time sandbox
    health probe so registration stays truthful when the sandbox is unavailable.
    """
    if backend is None or backend.location != "server":
        return False
    if not settings.gvisor_enabled:
        return False
    from agentcore.tools.sandbox.cloud_health import cloud_sandbox_health

    return cloud_sandbox_health() is not False


def build_builtin_registry(
    *,
    include_execution_tools: bool = True,
    location: Literal["server", "local"] | None = None,
    languages: tuple[str, ...] | list[str] | None = None,
) -> ToolRegistry:
    """Register the platform's built-in tools (single source: ``DECLARED_TOOLS``).

    Both the chat pipeline (worker toolset) and the read-only capability catalog
    build from declarations with ``surface=builtin``. CEO orchestration primitives
    and worker-only tools are separate surfaces.

    ``include_execution_tools`` gates the code-execution class as a unit
    (``test_run`` + ``code_execute``): the worker registry withholds BOTH on a backend
    that can't run code safely (see ``code_execution_enabled_for``).

    ``location`` stamps ``code_execute``'s description to match the turn's backend.
    ``languages`` trims ``code_execute``'s language enum after a local/sidecar probe
    (cloud / catalog leave ``None`` → full fixed surface).
    """
    registry = ToolRegistry()
    for cls in declared_tools(surface=ToolSurface.BUILTIN):
        reg = tool_registration(cls)
        if reg.execution_class and not include_execution_tools:
            continue
        registry.register(
            instantiate_declared(cls, location=location, languages=languages)
        )
    return registry


def build_worker_registry(
    *,
    backend: WorkspaceBackend | None = None,
    permission_preset: "PermissionPreset | None" = None,
    languages: tuple[str, ...] | list[str] | None = None,
) -> ToolRegistry:
    """The delegated worker's toolset: builtins PLUS worker-only declarations.

    ``permission_preset=observe`` withholds the entire execution class
    (``code_execute`` / ``test_run`` / ``terminal``) — read-only retrieval stays on.
    """
    location = backend.location if backend is not None else None
    include_execution = code_execution_enabled_for(backend)
    if permission_preset is PermissionPreset.OBSERVE:
        include_execution = False
    # Browser class needs gVisor cloud ON TOP of the execution-class gate (so OBSERVE
    # still withholds it, and a subprocess "sandbox" never gets a browser).
    include_browser = include_execution and browser_execution_enabled_for(backend)
    # Prefer explicit languages; else reuse a probe cached on the backend by
    # ``resolve_exec_languages`` (prepare / resume). Cloud stays untrimmed.
    resolved_languages = languages
    if resolved_languages is None and backend is not None:
        resolved_languages = getattr(backend, "_exec_languages", None)
    if location != "local":
        resolved_languages = None
    registry = build_builtin_registry(
        include_execution_tools=include_execution,
        location=location,
        languages=resolved_languages,
    )
    for cls in declared_tools(surface=ToolSurface.WORKER_ONLY):
        reg = tool_registration(cls)
        if reg.execution_class and not include_execution:
            continue
        if reg.browser_class and not include_browser:
            continue
        if reg.local_only and (backend is None or backend.location != "local"):
            continue
        registry.register(instantiate_declared(cls, location=location))
    return registry


def build_ceo_tool_registry() -> ToolRegistry:
    """The CEO chat agent's DIRECT toolset: read / retrieval builtins only.

    Collects ``surface=builtin`` tools whose declared audience includes ``ceo``
    (must stay aligned with ``approval=NEVER`` — enforced by snapshot tests).
    Orchestration primitives are wired separately in ``_assemble_ceo_toolset``.
    """
    full = build_builtin_registry()
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
