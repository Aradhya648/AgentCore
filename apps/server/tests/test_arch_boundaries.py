"""Architecture import-boundary guards (executable layering contract).

Encodes the dependency contracts from ``docs/02-架构/项目结构.md`` §二 as tests so
the refined boundaries can't silently erode again. Each test parses real source
files (via ``ast``) and asserts the absence of forbidden ``agentcore.*`` imports.

The contracts are deliberately *pragmatic*, not maximal (post-2026-06 META
review): they forbid the couplings that genuinely break layering — routes
*executing*, the LLM gateway reaching into the DB, ``core`` depending upward —
while allowing the documented benign ones (routes reusing pricing constants /
runtime DTOs / credential resolution; ``core`` depending on ``config``). When a
boundary legitimately needs to change, update *both* this test and the doc — that
paired edit is the point.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[1]
_PKG_ROOT = _SERVER_ROOT / "agentcore"


def _module_imports(path: Path) -> set[str]:
    """All ``agentcore.*`` dotted module targets imported by a source file.

    ``from agentcore.llm.factory import build_provider`` -> ``agentcore.llm.factory``;
    ``import agentcore.db.x`` -> ``agentcore.db.x``. Relative imports are ignored
    (they can't cross top-level package boundaries).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.startswith("agentcore"):
                out.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("agentcore"):
                    out.add(alias.name)
    return out


def _py_files(*rel: str) -> list[Path]:
    """Resolve package-relative paths to ``.py`` files (file or recursive dir)."""
    files: list[Path] = []
    for r in rel:
        base = _PKG_ROOT / r
        if base.is_file():
            files.append(base)
        else:
            files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _violations(files: Iterable[Path], forbidden: Iterable[str]) -> dict[str, set[str]]:
    """Map ``relpath -> forbidden imports found``; empty dict == contract holds."""
    forbidden = tuple(forbidden)
    bad: dict[str, set[str]] = {}
    for f in files:
        hits = {
            imp
            for imp in _module_imports(f)
            for pref in forbidden
            if imp == pref or imp.startswith(pref + ".")
        }
        if hits:
            bad[str(f.relative_to(_PKG_ROOT))] = hits
    return bad


def test_api_routes_do_not_execute() -> None:
    """HTTP routes delegate; they never build LLM providers nor drive the pipeline.

    Routes legitimately import runtime DTOs/helpers, pricing constants and
    credential resolution (documented benign). But constructing a provider
    (``llm.factory``) or running the engine (``runtime.pipeline`` /
    ``runtime.engine``) belongs in the service/runtime layer — e.g. ``files.py``
    delegates rewriting to ``assist.rewrite`` instead of building a provider
    inline.
    """
    forbidden = (
        "agentcore.llm.factory",
        "agentcore.runtime.pipeline",
        "agentcore.runtime.engine",
    )
    files = [f for f in _py_files("api/routes") if "inference" not in f.parts]
    assert _violations(files, forbidden) == {}


def test_llm_gateway_does_not_import_db() -> None:
    """The LLM gateway is a pure outbound adapter — no DB/business coupling.

    The only exemptions are the credential bridge (``provider_service`` /
    ``resolve``), which intentionally read user-scoped providers from the DB to
    resolve BYOK creds.
    """
    bridge = {"provider_service.py", "resolve.py"}
    files = [f for f in _py_files("llm") if f.name not in bridge]
    assert _violations(files, ("agentcore.db",)) == {}


def test_core_has_no_upward_business_deps() -> None:
    """``core`` is the bottom layer: shared infra/types, zero business imports.

    It may depend on ``config`` (settings/logging/net wiring) but nothing above
    it — so ``core.net`` can host the shared SSRF/timeout primitives consumed by
    both the web tools and the favicon route without an ``api -> tools`` edge.
    """
    forbidden = (
        "agentcore.api",
        "agentcore.runtime",
        "agentcore.tools",
        "agentcore.llm",
        "agentcore.db",
        "agentcore.conversation",
        "agentcore.memory",
        "agentcore.board",
        "agentcore.evals",
        "agentcore.assist",
        "agentcore.vision",
        "agentcore.sidecar",
        "agentcore.conformance",
        "agentcore.workspace",
    )
    exempt = {"errors.py"}  # lazy-imports llm.errors for SSE error context projection
    files = [f for f in _py_files("core") if f.name not in exempt]
    assert _violations(files, forbidden) == {}


def test_leaf_web_tools_do_not_import_runtime_or_llm() -> None:
    """Leaf tools are self-contained — no reach into runtime/llm.

    (Orchestration primitives such as delegate/debate legitimately drive the
    runtime, so only the leaf web tools are asserted here.)
    """
    files = _py_files("tools/builtin/web")
    assert _violations(files, ("agentcore.runtime", "agentcore.llm")) == {}


def test_runtime_drive_and_coordination_do_not_import_tools_delegate() -> None:
    """Delegate drive / coordination sit in runtime — no tools.builtin.delegate edge.

    Composition roots (pipeline / resolve / recover) may still construct
    ``DelegateTool``; the forbidden cycle was ``coordination.host`` ↔
    ``tools.builtin.delegate.drive``. After the lift, ``runtime.delegate`` and
    ``runtime.coordination`` must not import the tools-side package at all.
    """
    files = _py_files("runtime/delegate", "runtime/coordination")
    assert _violations(files, ("agentcore.tools.builtin.delegate",)) == {}


def test_delegate_tools_package_is_thin_adapter() -> None:
    """``tools.builtin.delegate`` hosts schema + thin execute + nesting mint only."""
    allowed = {"__init__.py", "schema.py", "tool.py", "nesting.py"}
    present = {p.name for p in _py_files("tools/builtin/delegate")}
    assert present <= allowed, f"unexpected delegate tool modules: {present - allowed}"


def test_debate_tools_package_is_thin_adapter() -> None:
    """``tools.builtin.debate`` hosts schema + thin execute only；域逻辑在 runtime.debate。"""
    allowed = {"__init__.py", "schema.py", "tool.py"}
    present = {p.name for p in _py_files("tools/builtin/debate")}
    assert present <= allowed, f"unexpected debate tool modules: {present - allowed}"
    # 域驱动不得回留在 tools 包（rounds/prompt/events 已上收 runtime.debate）。
    assert not (present & {"rounds.py", "prompt.py", "events.py"})


def test_engine_stream_uses_public_retry_constants() -> None:
    """``engine.stream`` takes retry/backoff from ``llm.provider.protocol``, not privates."""
    stream = _PKG_ROOT / "runtime" / "engine" / "stream.py"
    imports = _module_imports(stream)
    assert "agentcore.llm.provider.protocol" in imports
    tree = ast.parse(stream.read_text(encoding="utf-8"), filename=str(stream))
    private_hits: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "agentcore.llm.provider.openai_compatible"
        ):
            for alias in node.names:
                if alias.name.startswith("_"):
                    private_hits.add(alias.name)
    assert private_hits == set(), f"stream imports provider privates: {private_hits}"
    src = stream.read_text(encoding="utf-8")
    assert "MAX_RETRIES" in src
    assert "INITIAL_BACKOFF" in src
    assert "BACKOFF_MULTIPLIER" in src
