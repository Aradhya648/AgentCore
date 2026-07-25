"""Git operations tool — read and write git state within the workspace.

Thin shell over subprocess git in the workspace root (``ServerWorkspace.root``).
Read subcommands (status / diff / log) run without approval; write subcommands
(add / commit / branch / checkout) are refused on the CEO path and executed on
delegated workers. Dangerous operations (push / reset / rebase / …) are hard-
rejected at the tool boundary.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from agentcore.core.text import truncate_head_tail
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.safety_breaker import (
    git_forbidden_subcommands,
    git_protected_branches,
)
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_BOTH,
    ToolRegistration,
    ToolSurface,
)

_ALLOWED_SUBCOMMANDS = frozenset(
    {"status", "diff", "log", "add", "commit", "branch", "checkout"}
)
_WRITE_SUBCOMMANDS = frozenset({"add", "commit", "branch", "checkout"})


def git_write_subcommands() -> frozenset[str]:
    """Git subcommands that mutate repo state and require user approval on workers."""
    return _WRITE_SUBCOMMANDS


# Hard-ban list lives in ``runtime.safety_breaker`` (P3 unified circuit breaker).
_FORBIDDEN_PATTERNS = git_forbidden_subcommands()
_PROTECTED_BRANCHES = git_protected_branches()
_DIFF_OUTPUT_LIMIT = 16000
_GIT_TIMEOUT = 25.0

GIT_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subcommand": {
            "type": "string",
            "enum": ["status", "diff", "log", "add", "commit", "branch", "checkout"],
            "description": "要执行的 git 子命令。",
        },
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "status/diff/add 的路径过滤（工作区相对路径）。add 时必填。",
        },
        "staged": {
            "type": "boolean",
            "description": "diff 时只看暂存区（等同 git diff --cached）。默认 false。",
            "default": False,
        },
        "max_count": {
            "type": "integer",
            "description": "log 最多返回条数（默认 20，上限 100）。",
            "default": 20,
        },
        "oneline": {
            "type": "boolean",
            "description": "log 使用 --oneline 格式。默认 true。",
            "default": True,
        },
        "message": {
            "type": "string",
            "description": "commit 的提交说明（subcommand=commit 时必填）。",
        },
        "branch": {
            "type": "string",
            "description": "branch/checkout 的分支名（subcommand=branch 或 checkout 时必填）。",
        },
        "create": {
            "type": "boolean",
            "description": "checkout 时创建新分支（-b）。默认 false。",
            "default": False,
        },
    },
    "required": ["subcommand"],
}


def _error(error: str, start: float) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        success=False,
        output="",
        error=error,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def _ok(output: str, start: float, **kwargs: Any) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        success=True,
        output=output,
        duration_ms=int((time.monotonic() - start) * 1000),
        **kwargs,
    )


def _resolve_git_cwd(context: ToolContext) -> str | None:
    """Return the absolute workspace root for git, when available."""
    root = getattr(context.backend, "root", None)
    if root is not None:
        # Always absolute so GIT_CEILING_DIRECTORIES matches the process cwd.
        return str(Path(root).resolve())
    return None


def _workspace_has_local_git(cwd: str) -> bool:
    """True only when ``.git`` exists *inside* the workspace root (no parent climb)."""
    return (Path(cwd) / ".git").exists()


def _is_ceo_context(context: ToolContext) -> bool:
    """CEO turns carry no worker-only coordination channels."""
    return (
        context.write_coordinator is None
        and context.note_wall is None
        and context.escalation is None
    )


async def _run_git(
    args: list[str], *, cwd: str, timeout: float = _GIT_TIMEOUT
) -> tuple[str, str, int]:
    """Run git command, return (stdout, stderr, exit_code).

    ``GIT_CEILING_DIRECTORIES`` is set to the workspace root so discovery never
    climbs into a parent repo (e.g. workspace nested under the host monorepo).
    """
    ceiling = str(Path(cwd).resolve())
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CEILING_DIRECTORIES": ceiling,
    }
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return "", "git 操作超时", 1
    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
        proc.returncode or 0,
    )


async def _git_failure(
    stdout: str, stderr: str, exit_code: int, start: float
) -> ToolResult:
    detail = (stderr or stdout or f"git 退出码 {exit_code}").strip()
    return _error(detail, start)


_NO_LOCAL_REPO_MSG = (
    "当前工作区内没有 Git 仓库（仅识别工作区根下的 .git；不会上溯到父目录仓库）"
)


async def _ensure_git_repo(cwd: str, start: float) -> ToolResult | None:
    # Fast path: refuse before any git discovery that could surface a parent repo.
    if not _workspace_has_local_git(cwd):
        return _error(_NO_LOCAL_REPO_MSG, start)
    stdout, stderr, code = await _run_git(
        ["rev-parse", "--is-inside-work-tree"], cwd=cwd
    )
    if code != 0 or stdout.strip() != "true":
        detail = (stderr or stdout or _NO_LOCAL_REPO_MSG).strip()
        return _error(detail, start)
    return None


async def _current_branch(cwd: str) -> str:
    stdout, _, code = await _run_git(["branch", "--show-current"], cwd=cwd)
    if code != 0:
        return ""
    return stdout.strip()


def _validate_add_paths(paths: list[Any], start: float) -> ToolResult | None:
    if not paths:
        return _error("add 需要显式 paths 参数，禁止使用 git add . / -A / --all", start)
    forbidden = {".", "-A", "--all"}
    for raw in paths:
        path = str(raw).strip()
        if not path:
            return _error("add 的 paths 不能包含空路径", start)
        if path in forbidden:
            return _error(
                f"禁止 add 路径 '{path}'：请显式列出文件，不要使用 . / -A / --all",
                start,
            )
        if "*" in path or "?" in path:
            return _error(f"禁止 add 通配符路径 '{path}'：请显式列出文件", start)
    return None


def _normalize_paths(raw_paths: Any) -> list[str]:
    if not raw_paths:
        return []
    return [str(p) for p in raw_paths if str(p).strip()]


class GitTool:
    """Execute git subcommands within the workspace root."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_BOTH,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="git",
            description=(
                "在工作区内执行 Git 操作。只读：status（工作区状态）、diff（差异）、"
                "log（提交历史）。写入（需用户授权）：add（暂存）、commit（提交）、"
                "branch（创建分支）、checkout（切换分支）。"
                "禁止 push / reset / rebase 等危险操作——推送由用户手动完成。"
            ),
            parameters=GIT_TOOL_PARAMETERS,
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.NEVER,
            timeout_seconds=30.0,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        subcommand = str(arguments.get("subcommand", "")).strip().lower()

        if not subcommand:
            return _error("subcommand 为必填参数", start)
        if subcommand not in _ALLOWED_SUBCOMMANDS:
            return _error(f"子命令 '{subcommand}' 不在允许列表中", start)
        if any(pattern in subcommand for pattern in _FORBIDDEN_PATTERNS):
            return _error(f"子命令 '{subcommand}' 被安全策略拒绝", start)

        if subcommand in _WRITE_SUBCOMMANDS and _is_ceo_context(context):
            return _error("Git 写入操作需通过 delegate 委派给 Worker 执行。", start)

        cwd = _resolve_git_cwd(context)
        if cwd is None:
            return _error("当前工作区模式不支持 Git 操作（无本地根目录）", start)

        repo_err = await _ensure_git_repo(cwd, start)
        if repo_err is not None:
            return repo_err

        paths = _normalize_paths(arguments.get("paths"))

        if subcommand == "status":
            return await self._cmd_status(cwd, paths, start)
        if subcommand == "diff":
            staged = bool(arguments.get("staged", False))
            return await self._cmd_diff(cwd, paths, staged=staged, start=start)
        if subcommand == "log":
            max_count = int(arguments.get("max_count", 20))
            max_count = max(1, min(max_count, 100))
            oneline = bool(arguments.get("oneline", True))
            return await self._cmd_log(cwd, paths, max_count=max_count, oneline=oneline, start=start)
        if subcommand == "add":
            return await self._cmd_add(cwd, paths, start)
        if subcommand == "commit":
            message = str(arguments.get("message", "")).strip()
            return await self._cmd_commit(cwd, message, start)
        if subcommand == "branch":
            branch = str(arguments.get("branch", "")).strip()
            return await self._cmd_branch(cwd, branch, start)
        if subcommand == "checkout":
            branch = str(arguments.get("branch", "")).strip()
            create = bool(arguments.get("create", False))
            return await self._cmd_checkout(cwd, branch, create=create, start=start)

        return _error(f"子命令 '{subcommand}' 不在允许列表中", start)

    async def _cmd_status(self, cwd: str, paths: list[str], start: float) -> ToolResult:
        branch = await _current_branch(cwd)
        branch_line = branch or "(无)"
        args = ["status", "--short"]
        if paths:
            args.extend(["--", *paths])
        stdout, stderr, code = await _run_git(args, cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start)
        body = stdout.rstrip()
        output = f"## 当前分支: {branch_line}\n"
        output += body if body else "（工作区干净）"
        return _ok(output, start)

    async def _cmd_diff(
        self, cwd: str, paths: list[str], *, staged: bool, start: float
    ) -> ToolResult:
        args = ["diff"]
        if staged:
            args.append("--cached")
        if paths:
            args.extend(["--", *paths])
        stdout, stderr, code = await _run_git(args, cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start)
        output = stdout.rstrip() or "（无差异）"
        if len(output) > _DIFF_OUTPUT_LIMIT:
            output = truncate_head_tail(output, _DIFF_OUTPUT_LIMIT)
        return _ok(output, start, output_limit=_DIFF_OUTPUT_LIMIT)

    async def _cmd_log(
        self,
        cwd: str,
        paths: list[str],
        *,
        max_count: int,
        oneline: bool,
        start: float,
    ) -> ToolResult:
        args = ["log", f"-n{max_count}"]
        if oneline:
            args.append("--oneline")
        if paths:
            args.extend(["--", *paths])
        stdout, stderr, code = await _run_git(args, cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start)
        lines = [line for line in stdout.splitlines() if line.strip()]
        body = "\n".join(lines) if lines else "（无提交记录）"
        footer = f"\n\n（共 {len(lines)} 条，可用 max_count 调整）"
        return _ok(body + footer, start)

    async def _cmd_add(self, cwd: str, paths: list[str], start: float) -> ToolResult:
        path_err = _validate_add_paths(paths, start)
        if path_err is not None:
            return path_err
        args = ["add", "--", *paths]
        stdout, stderr, code = await _run_git(args, cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start)
        listed = ", ".join(paths)
        detail = (stdout or stderr).strip()
        output = f"已暂存：{listed}"
        if detail:
            output += f"\n{detail}"
        return _ok(output, start)

    async def _cmd_commit(self, cwd: str, message: str, start: float) -> ToolResult:
        if not message:
            return _error("commit 需要 message 参数", start)
        branch = await _current_branch(cwd)
        if branch in _PROTECTED_BRANCHES:
            return _error(
                "禁止在 main/master 分支直接提交，请先 checkout 到功能分支",
                start,
            )
        stdout, stderr, code = await _run_git(["commit", "-m", message], cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start)
        sha, _, sha_code = await _run_git(["rev-parse", "--short", "HEAD"], cwd=cwd)
        short_sha = sha.strip() if sha_code == 0 else ""
        output = f"已提交 {short_sha}：{message}" if short_sha else f"已提交：{message}"
        detail = (stdout or stderr).strip()
        if detail:
            output += f"\n{detail}"
        return _ok(output, start)

    async def _cmd_branch(self, cwd: str, branch: str, start: float) -> ToolResult:
        if not branch:
            return _error("branch 需要 branch 参数", start)
        if branch.startswith("-"):
            return _error("分支名不能以 '-' 开头（防止被 git 解析为选项）", start)
        stdout, stderr, code = await _run_git(["branch", branch], cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start)
        detail = (stdout or stderr).strip()
        output = f"已创建分支 {branch}"
        if detail:
            output += f"\n{detail}"
        return _ok(output, start)

    async def _cmd_checkout(
        self, cwd: str, branch: str, *, create: bool, start: float
    ) -> ToolResult:
        if not branch:
            return _error("checkout 需要 branch 参数", start)
        if branch.startswith("-"):
            return _error("分支名不能以 '-' 开头（防止被 git 解析为选项）", start)
        args = ["checkout"]
        if create:
            args.extend(["-b", branch])
        else:
            args.append(branch)
        stdout, stderr, code = await _run_git(args, cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start)
        action = "已创建并切换到分支" if create else "已切换到分支"
        detail = (stdout or stderr).strip()
        output = f"{action} {branch}"
        if detail:
            output += f"\n{detail}"
        return _ok(output, start)
