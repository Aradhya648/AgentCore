"""Test runner tool — run workspace test suites with structured output."""

from __future__ import annotations

import os
import shlex
import time
from typing import Any, Literal

from agentcore.core.errors import SandboxError
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.context.workspace_profile import WorkspaceProfile, detect_workspace_profile
from agentcore.tools.builtin.code_execute import _permission_allows_restricted_network
from agentcore.tools.builtin.test_parsers import (
    TestRunResult,
    parse_generic_output,
    parse_jest_output,
    parse_pytest_output,
    parse_vitest_output,
)
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)
from agentcore.tools.sandbox.protocol import ExecutionRequest
from agentcore.workspace.protocol import PathNotFound, WorkspaceBackend

Framework = Literal["pytest", "vitest", "jest"]
Scope = Literal["all", "affected", "file"]

TEST_RUN_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scope": {
            "type": "string",
            "enum": ["all", "affected", "file"],
            "default": "affected",
            "description": (
                "测试范围：all=全量测试套件；affected=只跑可能受影响的测试"
                "（基于最近修改的文件）；file=指定单个测试文件。"
            ),
        },
        "test_file": {
            "type": "string",
            "description": "scope=file 时必填，测试文件的工作区相对路径。",
        },
        "framework": {
            "type": "string",
            "enum": ["pytest", "vitest", "jest", "auto"],
            "default": "auto",
            "description": "测试框架。auto 时从 WorkspaceProfile 自动检测。",
        },
        "filter": {
            "type": "string",
            "description": "可选，测试名过滤表达式（如 pytest 的 -k 参数值）。",
        },
    },
    "required": [],
}

_ALLOWED_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("npx", "vitest"),
    ("npx", "jest"),
    ("pnpm", "test"),
    ("npm", "test"),
    ("uv", "run", "pytest"),
    ("vitest",),
    ("jest",),
)

_VITEST_CONFIG_NAMES = (
    "vitest.config.ts",
    "vitest.config.js",
    "vitest.config.mts",
    "vitest.config.mjs",
)
_JEST_CONFIG_NAMES = (
    "jest.config.js",
    "jest.config.ts",
    "jest.config.mjs",
    "jest.config.cjs",
)

_SOURCE_EXTENSIONS = frozenset({".py", ".ts", ".tsx", ".js", ".jsx"})
_MAX_AFFECTED_SOURCES = 10
_DEFAULT_TIMEOUT = 120


def _make_output_callback(context: ToolContext):
    on_progress = context.on_progress
    if not on_progress:
        return None

    def callback(stream: str, chunk: str) -> None:
        on_progress("output", {"stream": stream, "chunk": chunk})

    return callback


def _is_allowed_command(argv: list[str]) -> bool:
    if not argv:
        return False
    for prefix in _ALLOWED_PREFIXES:
        if len(argv) >= len(prefix) and tuple(argv[: len(prefix)]) == prefix:
            return True
    return False


def _argv_to_shell(argv: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in argv)


def _is_test_file(path: str) -> bool:
    norm = path.replace("\\", "/")
    base = os.path.basename(norm)
    if base.startswith("test_") or base.endswith("_test.py"):
        return True
    if ".test." in base or ".spec." in base:
        return True
    if "/tests/" in norm or norm.startswith("tests/"):
        return True
    return "/__tests__/" in norm


def _is_source_file(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in _SOURCE_EXTENSIONS


async def _file_exists(backend: WorkspaceBackend, path: str) -> bool:
    try:
        await backend.read(path)
        return True
    except (PathNotFound, Exception):
        return False


async def _detect_framework(
    backend: WorkspaceBackend,
    profile: WorkspaceProfile,
    framework_arg: str,
) -> Framework | None:
    if framework_arg in ("pytest", "vitest", "jest"):
        return framework_arg  # type: ignore[return-value]

    for cmd in profile.test_commands:
        lowered = cmd.lower()
        if "pytest" in lowered:
            return "pytest"
        if "vitest" in lowered:
            return "vitest"
        if "jest" in lowered or "npm test" in lowered or "pnpm test" in lowered:
            return "jest"

    for name in _VITEST_CONFIG_NAMES:
        if await _file_exists(backend, name):
            return "vitest"

    for name in _JEST_CONFIG_NAMES:
        if await _file_exists(backend, name):
            return "jest"

    if await _file_exists(backend, "pyproject.toml"):
        return "pytest"

    if await _file_exists(backend, "package.json"):
        return "jest"

    return None


def _base_command(framework: Framework, profile: WorkspaceProfile) -> list[str]:
    if framework == "pytest":
        if "uv" in profile.package_managers:
            return ["uv", "run", "pytest", "--tb=short", "-q"]
        return ["pytest", "--tb=short", "-q"]
    if framework == "vitest":
        return ["npx", "vitest", "run"]
    return ["npx", "jest"]


def _infer_test_candidates(source_path: str) -> list[str]:
    norm = source_path.replace("\\", "/")
    base = os.path.basename(norm)
    stem, ext = os.path.splitext(base)
    dir_part = os.path.dirname(norm)

    if ext.lower() == ".py":
        candidates = [
            f"test_{stem}.py",
            f"tests/test_{stem}.py",
            f"{stem}_test.py",
        ]
        if dir_part:
            candidates.insert(0, f"{dir_part}/test_{stem}.py")
        return candidates

    if ext.lower() in (".ts", ".tsx", ".js", ".jsx"):
        suffix = ext
        in_dir = [
            f"{stem}.test{suffix}",
            f"{stem}.spec{suffix}",
        ]
        if dir_part:
            in_dir = [f"{dir_part}/{name}" for name in in_dir]
        return in_dir + [
            f"__tests__/{stem}.test{suffix}",
            f"tests/{stem}.test{suffix}",
        ]

    return []


async def _resolve_affected_paths(backend: WorkspaceBackend) -> list[str]:
    index = getattr(backend, "index_files", None)
    if index is None:
        return []

    try:
        paths, _ = await index(cap=50, order="recent")
    except Exception:
        return []

    sources = [p for p in paths if _is_source_file(p) and not _is_test_file(p)]
    test_paths: list[str] = []
    for src in sources[:_MAX_AFFECTED_SOURCES]:
        for candidate in _infer_test_candidates(src):
            if await _file_exists(backend, candidate):
                test_paths.append(candidate)
                break
    return list(dict.fromkeys(test_paths))


def _append_filter(argv: list[str], framework: Framework, filter_expr: str) -> list[str]:
    if not filter_expr.strip():
        return argv
    if framework == "pytest":
        return [*argv, "-k", filter_expr]
    return [*argv, "--testNamePattern", filter_expr]


def _parse_output(
    framework: Framework,
    stdout: str,
    stderr: str,
    exit_code: int,
) -> TestRunResult:
    if framework == "pytest":
        result = parse_pytest_output(stdout, stderr)
    elif framework == "vitest":
        result = parse_vitest_output(stdout, stderr)
    else:
        result = parse_jest_output(stdout, stderr)

    if (
        result.passed == 0
        and result.failed == 0
        and result.errors == 0
        and (exit_code != 0 or not result.failures)
    ):
        return parse_generic_output(stdout, stderr, exit_code)
    return result


def _format_output(
    result: TestRunResult,
    command_argv: list[str],
    duration_seconds: float,
) -> str:
    parts: list[str] = []
    header_counts = [f"{result.passed} passed"]
    if result.failed:
        header_counts.append(f"{result.failed} failed")
    if result.errors:
        header_counts.append(f"{result.errors} error")
    parts.append(f"## 测试结果：{', '.join(header_counts)}")

    if result.failures:
        parts.append("\n### 失败用例\n")
        for failure in result.failures:
            loc = failure.test_name
            if failure.file_path:
                loc = failure.file_path
                if failure.line is not None:
                    loc = f"{failure.file_path}:{failure.line}"
                loc = f"{failure.test_name} ({loc})"
            line = f"❌ {loc}"
            if failure.message:
                line += f"\n   {failure.message}"
            if failure.snippet:
                line += f"\n   > {failure.snippet}"
            parts.append(line)

    parts.append("\n### 摘要")
    parts.append(f"- 框架：{result.framework}")
    parts.append(f"- 命令：{_argv_to_shell(command_argv)}")
    if result.duration_seconds is not None:
        parts.append(f"- 耗时：{result.duration_seconds:.1f}s")
    elif duration_seconds > 0:
        parts.append(f"- 耗时：{duration_seconds:.1f}s")
    parts.append(
        f"- 通过：{result.passed} / 失败：{result.failed} / 错误：{result.errors}"
    )
    if result.skipped:
        parts.append(f"- 跳过：{result.skipped}")

    if result.failed or result.errors:
        parts.append("\n（用 file_read 查看失败测试的完整上下文）")
    elif result.framework == "unknown" and result.raw_output:
        parts.append("\n### 原始输出\n")
        parts.append(result.raw_output)

    return "\n".join(parts)


class TestRunTool:
    """Run the workspace test suite and return structured results."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
        execution_class=True,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="test_run",
            description=(
                "运行工作区的测试套件并返回结构化结果。自动检测测试框架（pytest / vitest / jest）"
                "并解析输出为通过/失败/错误摘要。适合验证代码改动是否正确。"
                "若只需执行任意命令，请用 code_execute。"
            ),
            parameters=TEST_RUN_PARAMETERS,
            category=ToolCategory.EXECUTION,
            # test_run runs the project's test command through the SAME sandbox chain as
            # code_execute (context.backend.execute) — a test suite executes arbitrary
            # project code (conftest, fixtures, plugins), so its execution power is
            # equivalent. It therefore belongs to the same code-execution class and must
            # carry the SAME governance: GRANTABLE so the approval gate covers it, the CEO
            # NEVER-filter keeps it worker-only, and the cloud availability gate
            # (code_execution_enabled_for) withholds it where the sandbox isn't a real
            # isolation boundary — closing the P0 where a NEVER test_run ran ungated
            # (local: user's real machine; cloud default: subprocess RCE). Turn grants
            # are allowed (per_call_tool_names empty, Cursor-aligned).
            approval=ToolApproval.GRANTABLE,
            timeout_seconds=_DEFAULT_TIMEOUT,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        scope: Scope = arguments.get("scope", "affected")  # type: ignore[assignment]
        test_file = (arguments.get("test_file") or "").strip()
        framework_arg = arguments.get("framework", "auto")
        filter_expr = (arguments.get("filter") or "").strip()

        if scope == "file" and not test_file:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error="scope=file 时必须提供 test_file 参数",
                duration_ms=0,
            )

        profile = await detect_workspace_profile(context.backend)
        framework = await _detect_framework(context.backend, profile, framework_arg)
        if framework is None:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=(
                    "无法检测测试框架。请确认工作区包含 pyproject.toml（pytest）、"
                    "vitest.config.* 或 jest.config.*，或在 framework 参数中显式指定。"
                ),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        argv = _base_command(framework, profile)
        argv = _append_filter(argv, framework, filter_expr)

        if scope == "file":
            argv.append(test_file)
        elif scope == "affected":
            affected = await _resolve_affected_paths(context.backend)
            if affected:
                argv.extend(affected)
            elif framework == "pytest":
                argv.append("tests/")
        # scope == "all": no path args

        if not _is_allowed_command(argv):
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=f"命令不在白名单内：{_argv_to_shell(argv)}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        command_shell = _argv_to_shell(argv)
        request = ExecutionRequest(
            code=command_shell,
            language="bash",
            timeout_seconds=_DEFAULT_TIMEOUT,
            on_output=_make_output_callback(context),
            network_mode=(
                "restricted"
                if _permission_allows_restricted_network(context.permission_preset)
                else "none"
            ),
        )

        if context.on_phase:
            context.on_phase("executing")

        try:
            exec_result = await context.backend.execute(request)
        except SandboxError as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            msg = e.message or str(e)
            return ToolResult(
                tool_call_id="",
                success=False,
                output=msg,
                error=msg,
                duration_ms=duration_ms,
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        duration_s = duration_ms / 1000.0

        parsed = _parse_output(
            framework,
            exec_result.stdout,
            exec_result.stderr,
            exec_result.exit_code,
        )
        if parsed.duration_seconds is None and exec_result.duration_ms:
            parsed.duration_seconds = exec_result.duration_ms / 1000.0

        output = _format_output(parsed, argv, duration_s)
        tests_passed = parsed.failed == 0 and parsed.errors == 0 and exec_result.exit_code == 0

        display = {
            "framework": parsed.framework,
            "command": command_shell,
            "passed": parsed.passed,
            "failed": parsed.failed,
            "errors": parsed.errors,
            "skipped": parsed.skipped,
            "exit_code": exec_result.exit_code,
            "stdout": exec_result.stdout,
            "stderr": exec_result.stderr,
            "failures": [
                {
                    "test_name": f.test_name,
                    "file_path": f.file_path,
                    "line": f.line,
                    "message": f.message,
                    "snippet": f.snippet,
                }
                for f in parsed.failures
            ],
        }

        return ToolResult(
            tool_call_id="",
            success=tests_passed,
            output=output,
            error=None if tests_passed else f"测试未通过（退出码 {exec_result.exit_code}）",
            duration_ms=duration_ms,
            metadata={
                "framework": parsed.framework,
                "passed": parsed.passed,
                "failed": parsed.failed,
                "errors": parsed.errors,
            },
            display=display,
        )
