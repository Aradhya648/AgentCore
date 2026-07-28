"""Bounded project verification — test / typecheck / build with a minute-level budget.

Expands the historical ``test_run`` surface into the first-class verify tool of the
short-exec / bounded-verify / long-running triad:

- ``code_execute`` — short, self-exiting scripts only
- **this tool** — project checks (test / typecheck / build / explicit verify command)
- ``terminal`` — long-running processes

Runs through the same sandbox chain and GRANTABLE posture as ``code_execute``.
Over-budget timeouts are ``contract_failure`` (verify incomplete), not circuit-breaker
fuel. Local runs launch via a Python argv runner so Windows never defaults through a
WSL bash trampoline.
"""

from __future__ import annotations

import os
import re
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
from agentcore.tools.sandbox.protocol import ExecutionRequest, ExecutionResult
from agentcore.workspace.protocol import PathNotFound, WorkspaceBackend

Framework = Literal["pytest", "vitest", "jest"]
Scope = Literal["all", "affected", "file"]
CheckKind = Literal["test", "typecheck", "build", "command"]

# Minute-level verify budget. Engine schema timeout adds slack so the sandbox
# returns Timeout first and we can mark ``contract_failure`` (not engine cancel).
_VERIFY_BUDGET_SECONDS = 300
_ENGINE_TIMEOUT_SLACK_SECONDS = 30
_DEFAULT_TIMEOUT = _VERIFY_BUDGET_SECONDS

TEST_RUN_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "check": {
            "type": "string",
            "enum": ["test", "typecheck", "build", "command"],
            "default": "test",
            "description": (
                "验证种类：test=测试套件；typecheck=类型检查（tsc 等）；"
                "build=项目构建；command=显式跑 command（用于 completion_criteria / "
                "verify_command）。慢 build / 全量 tsc / 项目测试请用本工具，勿用 "
                "code_execute。"
            ),
        },
        "command": {
            "type": "string",
            "description": (
                "check=command 时必填：要跑的验证命令（如 pnpm test、npx tsc --noEmit、"
                "npm run build）。须为项目检查形，禁止长驻进程。"
            ),
        },
        "scope": {
            "type": "string",
            "enum": ["all", "affected", "file"],
            "default": "affected",
            "description": (
                "仅 check=test：all=全量；affected=受影响测试；file=单个测试文件。"
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
            "description": "仅 check=test：测试框架。auto 时从 WorkspaceProfile 自动检测。",
        },
        "filter": {
            "type": "string",
            "description": "仅 check=test：可选测试名过滤（如 pytest -k）。",
        },
        "purpose": {
            "type": "string",
            "description": (
                "一句话中文说明这次验证要确认什么；会展示给用户作为审批说明，执行时忽略"
            ),
        },
    },
    "required": [],
}

_ALLOWED_PREFIXES: tuple[tuple[str, ...], ...] = (
    # tests
    ("pytest",),
    ("python", "-m", "pytest"),
    ("npx", "vitest"),
    ("npx", "jest"),
    ("pnpm", "test"),
    ("npm", "test"),
    ("yarn", "test"),
    ("uv", "run", "pytest"),
    ("vitest",),
    ("jest",),
    # typecheck / build
    ("tsc",),
    ("npx", "tsc"),
    ("vue-tsc",),
    ("npx", "vue-tsc"),
    ("npm", "run", "typecheck"),
    ("npm", "run", "type-check"),
    ("npm", "run", "build"),
    ("npm", "run", "lint"),
    ("pnpm", "run", "typecheck"),
    ("pnpm", "run", "type-check"),
    ("pnpm", "run", "build"),
    ("pnpm", "run", "lint"),
    ("pnpm", "typecheck"),
    ("pnpm", "build"),
    ("yarn", "typecheck"),
    ("yarn", "build"),
    ("yarn", "run", "typecheck"),
    ("yarn", "run", "build"),
    ("cargo", "test"),
    ("cargo", "check"),
    ("cargo", "build"),
    ("go", "test"),
    ("go", "build"),
    ("python", "-m", "mypy"),
    ("mypy",),
    ("uv", "run", "mypy"),
)

# Mirrors completion._VERIFY_COMMAND_RE — keep allow surface honest for explicit command=.
_VERIFY_SHAPED_RE = re.compile(
    r"\b(?:"
    r"tsc\b|vue-tsc\b|typecheck\b|"
    r"(?:npm|pnpm|yarn)\s+run\s+(?:test|typecheck|type-check|build|lint)\b|"
    r"(?:npm|pnpm|yarn)\s+test\b|"
    r"pytest\b|vitest\b|\bjest\b|mypy\b|"
    r"cargo\s+(?:test|check|build)\b|go\s+(?:test|build)\b|"
    r"(?:mvn|gradlew?)\s+test\b"
    r")",
    re.IGNORECASE,
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

_TIMEOUT_MARKER = "Timeout: execution exceeded"


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


def _is_allowed_verify_argv(argv: list[str]) -> bool:
    if _is_allowed_command(argv):
        return True
    return bool(_VERIFY_SHAPED_RE.search(_argv_to_shell(argv)))


def _argv_to_shell(argv: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in argv)


def _parse_command(command: str) -> list[str] | None:
    text = command.strip()
    if not text:
        return None
    try:
        argv = shlex.split(text, posix=True)
    except ValueError:
        return None
    return argv or None


def _python_argv_runner(argv: list[str]) -> str:
    """Run ``argv`` under Python so local Windows never needs a bash trampoline."""
    return (
        "import shutil\n"
        "import subprocess\n"
        "import sys\n"
        f"argv = {list(argv)!r}\n"
        "resolved = shutil.which(argv[0])\n"
        "if resolved:\n"
        "    argv = [resolved, *argv[1:]]\n"
        "if sys.platform == 'win32' and argv[0].lower().endswith(('.cmd', '.bat')):\n"
        "    completed = subprocess.run(subprocess.list2cmdline(argv), shell=True)\n"
        "else:\n"
        "    completed = subprocess.run(argv)\n"
        "raise SystemExit(completed.returncode)\n"
    )


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


def _format_test_output(
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


def _format_check_output(
    *,
    check: CheckKind,
    command_argv: list[str],
    exec_result: ExecutionResult,
    duration_seconds: float,
    budget_exceeded: bool,
) -> str:
    if budget_exceeded:
        status = "未完成（预算耗尽）"
    elif exec_result.exit_code == 0:
        status = "通过"
    else:
        status = "未通过"
    parts = [
        f"## 验证结果：{status}",
        "",
        "### 摘要",
        f"- 种类：{check}",
        f"- 命令：{_argv_to_shell(command_argv)}",
        f"- 退出码：{exec_result.exit_code}",
        f"- 耗时：{duration_seconds:.1f}s",
        f"- 预算：{_VERIFY_BUDGET_SECONDS}s",
    ]
    if budget_exceeded:
        parts.append(
            f"- 说明：验证未在 {_VERIFY_BUDGET_SECONDS}s 预算内完成；"
            "这是验证未完成，不是执行工具故障。可缩小范围、换更快的 check，或拆命令后重试。"
        )
    raw = (exec_result.stdout or "").strip()
    err = (exec_result.stderr or "").strip()
    if raw:
        parts.extend(["", "### stdout", raw])
    if err and not (budget_exceeded and _TIMEOUT_MARKER in err):
        parts.extend(["", "### stderr", err])
    elif err and budget_exceeded:
        # Keep the timeout line visible once.
        parts.extend(["", "### stderr", err])
    return "\n".join(parts)


def _is_budget_timeout(exec_result: ExecutionResult) -> bool:
    if exec_result.exit_code == -1 and _TIMEOUT_MARKER in (exec_result.stderr or ""):
        return True
    return _TIMEOUT_MARKER in (exec_result.stderr or "")


def _js_pm_run(profile: WorkspaceProfile, script: str) -> list[str]:
    pm = "npm"
    for candidate in ("pnpm", "yarn", "npm"):
        if candidate in profile.package_managers:
            pm = candidate
            break
    if pm == "yarn":
        return ["yarn", script]
    if pm == "pnpm":
        # Prefer bare script when common; fall back to run for custom names.
        if script in ("test", "build", "typecheck"):
            return ["pnpm", script] if script != "test" else ["pnpm", "test"]
        return ["pnpm", "run", script]
    return ["npm", "run", script] if script != "test" else ["npm", "test"]


async def _resolve_typecheck_argv(
    backend: WorkspaceBackend,
    profile: WorkspaceProfile,
) -> list[str] | None:
    for cmd in getattr(profile, "typecheck_commands", None) or []:
        argv = _parse_command(cmd)
        if argv and _is_allowed_verify_argv(argv):
            return argv
    if await _file_exists(backend, "tsconfig.json"):
        return ["npx", "tsc", "--noEmit"]
    return None


async def _resolve_build_argv(
    backend: WorkspaceBackend,
    profile: WorkspaceProfile,
) -> list[str] | None:
    for cmd in profile.build_commands:
        argv = _parse_command(cmd)
        if argv and _is_allowed_verify_argv(argv):
            return argv
    if profile.package_managers and await _file_exists(backend, "package.json"):
        return _js_pm_run(profile, "build")
    return None


async def _resolve_test_argv(
    *,
    backend: WorkspaceBackend,
    profile: WorkspaceProfile,
    arguments: dict[str, Any],
) -> tuple[list[str] | None, Framework | None, str | None]:
    scope: Scope = arguments.get("scope", "affected")  # type: ignore[assignment]
    test_file = (arguments.get("test_file") or "").strip()
    framework_arg = arguments.get("framework", "auto")
    filter_expr = (arguments.get("filter") or "").strip()

    if scope == "file" and not test_file:
        return None, None, "scope=file 时必须提供 test_file 参数"

    framework = await _detect_framework(backend, profile, framework_arg)
    if framework is None:
        return (
            None,
            None,
            (
                "无法检测测试框架。请确认工作区包含 pyproject.toml（pytest）、"
                "vitest.config.* 或 jest.config.*，或在 framework 参数中显式指定；"
                "或改用 check=command 并提供 verify 命令。"
            ),
        )

    argv = _base_command(framework, profile)
    argv = _append_filter(argv, framework, filter_expr)

    if scope == "file":
        argv.append(test_file)
    elif scope == "affected":
        affected = await _resolve_affected_paths(backend)
        if affected:
            argv.extend(affected)
        elif framework == "pytest":
            argv.append("tests/")
    return argv, framework, None


class TestRunTool:
    """Bounded project verification (test / typecheck / build / explicit command)."""

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
                "有界项目验证：跑工作区声明的检查（测试 / typecheck / build / 显式 "
                "verify 命令），分钟级预算、可流式输出。适合 completion_criteria="
                "code_verified 与慢 build、全量 tsc、项目测试——【不要】用 code_execute "
                "跑这些。超预算返回「验证未完成」，不是工具故障。长驻进程请用 terminal。"
            ),
            parameters=TEST_RUN_PARAMETERS,
            category=ToolCategory.EXECUTION,
            # Same sandbox chain + GRANTABLE posture as code_execute (P0): a project
            # check executes arbitrary project code, so governance must stay aligned.
            approval=ToolApproval.GRANTABLE,
            timeout_seconds=_VERIFY_BUDGET_SECONDS + _ENGINE_TIMEOUT_SLACK_SECONDS,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        check: CheckKind = arguments.get("check", "test")  # type: ignore[assignment]
        if check not in ("test", "typecheck", "build", "command"):
            check = "test"

        profile = await detect_workspace_profile(context.backend)
        framework: Framework | None = None
        err: str | None = None
        argv: list[str] | None = None

        if check == "command":
            raw_cmd = (arguments.get("command") or "").strip()
            if not raw_cmd:
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error="check=command 时必须提供 command 参数",
                    duration_ms=0,
                    contract_failure=True,
                    metadata={"code": "verify_contract"},
                )
            argv = _parse_command(raw_cmd)
            if argv is None:
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=f"无法解析 command：{raw_cmd}",
                    duration_ms=0,
                    contract_failure=True,
                    metadata={"code": "verify_contract"},
                )
        elif check == "typecheck":
            argv = await _resolve_typecheck_argv(context.backend, profile)
            if argv is None:
                err = (
                    "无法推断 typecheck 命令。请用 check=command 并提供命令"
                    "（如 npx tsc --noEmit），或确认存在 tsconfig.json / typecheck 脚本。"
                )
        elif check == "build":
            argv = await _resolve_build_argv(context.backend, profile)
            if argv is None:
                err = (
                    "无法推断 build 命令。请用 check=command 并提供命令"
                    "（如 npm run build），或确认 package.json 含 build 脚本。"
                )
        else:
            argv, framework, err = await _resolve_test_argv(
                backend=context.backend,
                profile=profile,
                arguments=arguments,
            )

        if err:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=err,
                duration_ms=int((time.monotonic() - start) * 1000),
                contract_failure=True,
                metadata={"code": "verify_contract"},
            )
        assert argv is not None

        if not _is_allowed_verify_argv(argv):
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=f"命令不在验证白名单内：{_argv_to_shell(argv)}",
                duration_ms=int((time.monotonic() - start) * 1000),
                contract_failure=True,
                metadata={"code": "verify_contract"},
            )

        command_shell = _argv_to_shell(argv)
        request = ExecutionRequest(
            code=_python_argv_runner(argv),
            language="python",
            timeout_seconds=_VERIFY_BUDGET_SECONDS,
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
        budget_exceeded = _is_budget_timeout(exec_result)

        if check == "test" and framework is not None and not budget_exceeded:
            parsed = _parse_output(
                framework,
                exec_result.stdout,
                exec_result.stderr,
                exec_result.exit_code,
            )
            if parsed.duration_seconds is None and exec_result.duration_ms:
                parsed.duration_seconds = exec_result.duration_ms / 1000.0
            output = _format_test_output(parsed, argv, duration_s)
            tests_passed = (
                parsed.failed == 0 and parsed.errors == 0 and exec_result.exit_code == 0
            )
            display = {
                "check": check,
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
                    "check": check,
                    "framework": parsed.framework,
                    "passed": parsed.passed,
                    "failed": parsed.failed,
                    "errors": parsed.errors,
                },
                display=display,
            )

        output = _format_check_output(
            check=check,
            command_argv=argv,
            exec_result=exec_result,
            duration_seconds=duration_s,
            budget_exceeded=budget_exceeded,
        )
        ok = (not budget_exceeded) and exec_result.exit_code == 0
        error: str | None
        if budget_exceeded:
            error = (
                f"验证未在 {_VERIFY_BUDGET_SECONDS}s 预算内完成（验证未完成，非工具故障）"
            )
        else:
            error = None if ok else f"验证未通过（退出码 {exec_result.exit_code}）"

        return ToolResult(
            tool_call_id="",
            success=ok,
            output=output,
            error=error,
            duration_ms=duration_ms,
            metadata={
                "check": check,
                "code": "verify_budget" if budget_exceeded else "verify_result",
                "timeout_seconds": _VERIFY_BUDGET_SECONDS,
                "exit_code": exec_result.exit_code,
            },
            display={
                "check": check,
                "command": command_shell,
                "exit_code": exec_result.exit_code,
                "stdout": exec_result.stdout,
                "stderr": exec_result.stderr,
                "budget_exceeded": budget_exceeded,
            },
            contract_failure=budget_exceeded,
        )
