"""Regression tests for TestRunTool command whitelist + framework detection.

Approval posture (GRANTABLE + turn-grantable + cloud withhold) is already pinned in
``test_approvals.py`` / ``test_tools_catalog.py`` — this file covers the execute-path
guards those suites do not: ``_ALLOWED_PREFIXES`` / ``_is_allowed_command`` and
``_detect_framework``. Do not re-assert the approval gate here.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.context.workspace_profile import WorkspaceProfile
from agentcore.tools.builtin.test_run import (
    _ALLOWED_PREFIXES,
    TestRunTool,
    _base_command,
    _detect_framework,
    _is_allowed_command,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.protocol import ExecutionRequest, ExecutionResult
from agentcore.workspace.protocol import PathNotFound


class _FakeBackend:
    """Minimal workspace stub: ``exists`` set controls which paths ``read`` finds."""

    def __init__(self, exists: set[str] | None = None) -> None:
        self._exists = exists or set()
        self.requests: list[ExecutionRequest] = []

    async def read(self, path: str) -> bytes:
        norm = path.replace("\\", "/")
        if norm in self._exists or path in self._exists:
            return b""
        raise PathNotFound(path)

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        return ExecutionResult(
            success=True, stdout="1 passed\n", stderr="", exit_code=0, duration_ms=1
        )

    async def index_files(self, *, cap: int = 50, order: str = "recent"):
        return [], 0


def _ctx(backend: _FakeBackend) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=backend,  # type: ignore[arg-type]
        user_id="u",
    )


def _make_profile(**kwargs: Any) -> WorkspaceProfile:
    defaults: dict[str, Any] = {
        "languages": [],
        "frameworks": [],
        "package_managers": [],
        "test_commands": [],
    }
    defaults.update(kwargs)
    return WorkspaceProfile(**defaults)


# --- approval posture (thin nail; full gate coverage lives in test_approvals) ---


def test_test_run_schema_stays_grantable_execution():
    """P0-1 regression nail: test_run must remain GRANTABLE ∩ EXECUTION.

    Full gate / turn-grant / cloud-withhold coverage is in test_approvals.py and
    test_tools_catalog.py — this only locks the tool class's own schema so a
    local NEVER regression cannot slip past without touching this file.
    """
    schema = TestRunTool().schema
    assert schema.name == "test_run"
    assert schema.approval is ToolApproval.GRANTABLE
    assert schema.category is ToolCategory.EXECUTION


# --- command whitelist ---


def test_allowed_prefixes_cover_supported_runners():
    # Pin the allowlist surface so a silent shrink (or accidental shell opener)
    # is caught. Prefixes are argv tuples matched from the left.
    prefixes = set(_ALLOWED_PREFIXES)
    assert ("pytest",) in prefixes
    assert ("python", "-m", "pytest") in prefixes
    assert ("uv", "run", "pytest") in prefixes
    assert ("npx", "vitest") in prefixes
    assert ("npx", "jest") in prefixes
    assert ("pnpm", "test") in prefixes
    assert ("npm", "test") in prefixes
    assert ("vitest",) in prefixes
    assert ("jest",) in prefixes


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "--tb=short", "-q"],
        ["python", "-m", "pytest", "-q"],
        ["uv", "run", "pytest", "--tb=short", "-q"],
        ["npx", "vitest", "run"],
        ["npx", "jest"],
        ["pnpm", "test"],
        ["npm", "test", "--", "foo"],
        ["vitest", "run"],
        ["jest", "--coverage"],
    ],
)
def test_is_allowed_command_accepts_whitelisted_prefixes(argv: list[str]):
    assert _is_allowed_command(argv) is True


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bash", "-c", "rm -rf /"],
        ["curl", "https://evil.example"],
        ["python", "-c", "import os; os.system('id')"],
        ["python", "script.py"],  # not ``python -m pytest``
        ["npx", "eslint"],  # npx alone is not enough — must be vitest/jest
        ["node", "-e", "1"],
        ["sh", "-c", "pytest"],
        ["sudo", "pytest"],
    ],
)
def test_is_allowed_command_rejects_non_whitelisted(argv: list[str]):
    assert _is_allowed_command(argv) is False


def test_base_command_always_produces_allowed_argv():
    for framework in ("pytest", "vitest", "jest"):
        for pm in ([], ["uv"], ["npm"]):
            argv = _base_command(framework, _make_profile(package_managers=pm))  # type: ignore[arg-type]
            assert _is_allowed_command(argv), (framework, pm, argv)


async def test_execute_rejects_when_command_leaves_whitelist(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend(exists={"pyproject.toml"})

    async def _fake_profile(_backend):
        return _make_profile(languages=["python"], test_commands=["pytest"])

    async def _framework(_backend, _prof, _arg):
        return "pytest"

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run._detect_framework",
        _framework,
    )
    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run._base_command",
        lambda *_a, **_k: ["bash", "-c", "evil"],
    )

    result = await TestRunTool().execute({"scope": "all"}, _ctx(backend))
    assert result.success is False
    assert "白名单" in (result.error or "")
    assert backend.requests == []  # never reached the sandbox


# --- framework detection ---


async def test_detect_framework_honors_explicit_arg():
    backend = _FakeBackend()
    assert await _detect_framework(backend, _make_profile(), "pytest") == "pytest"
    assert await _detect_framework(backend, _make_profile(), "vitest") == "vitest"
    assert await _detect_framework(backend, _make_profile(), "jest") == "jest"


async def test_detect_framework_from_profile_test_commands():
    backend = _FakeBackend()
    assert (
        await _detect_framework(
            backend, _make_profile(test_commands=["uv run pytest -q"]), "auto"
        )
        == "pytest"
    )
    assert (
        await _detect_framework(
            backend, _make_profile(test_commands=["npx vitest run"]), "auto"
        )
        == "vitest"
    )
    assert (
        await _detect_framework(
            backend, _make_profile(test_commands=["npm test"]), "auto"
        )
        == "jest"
    )


async def test_detect_framework_from_config_files():
    assert (
        await _detect_framework(
            _FakeBackend(exists={"vitest.config.ts"}), _make_profile(), "auto"
        )
        == "vitest"
    )
    assert (
        await _detect_framework(
            _FakeBackend(exists={"jest.config.js"}), _make_profile(), "auto"
        )
        == "jest"
    )
    assert (
        await _detect_framework(
            _FakeBackend(exists={"pyproject.toml"}), _make_profile(), "auto"
        )
        == "pytest"
    )
    assert (
        await _detect_framework(
            _FakeBackend(exists={"package.json"}), _make_profile(), "auto"
        )
        == "jest"
    )


async def test_detect_framework_returns_none_when_unknown():
    assert await _detect_framework(_FakeBackend(), _make_profile(), "auto") is None


async def test_execute_fails_cleanly_when_framework_undetectable(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend()

    async def _empty_profile(_backend):
        return _make_profile()

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _empty_profile,
    )

    result = await TestRunTool().execute({"scope": "all"}, _ctx(backend))
    assert result.success is False
    assert "无法检测测试框架" in (result.error or "")
    assert backend.requests == []


async def test_execute_requires_test_file_for_file_scope():
    result = await TestRunTool().execute(
        {"scope": "file"},
        _ctx(_FakeBackend()),
    )
    assert result.success is False
    assert "test_file" in (result.error or "")
