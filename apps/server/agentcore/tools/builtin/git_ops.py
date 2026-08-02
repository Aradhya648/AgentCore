"""Git operations tool — read and write git state within the workspace.

Thin shell over subprocess git in the workspace root (``ServerWorkspace.root``).
Read subcommands (status / diff / log) run without approval; write subcommands
(add / commit / branch / checkout / push) are refused on the CEO path and
executed on delegated workers (push requires user authorization). Dangerous
operations (reset / rebase / merge / …) are hard-rejected at the tool boundary.
Push itself is allowlisted but never force; main/master current branch is hard-
rejected; missing remote / credentials fail honestly (``GIT_TERMINAL_PROMPT=0``).

Timeout contract (aligned with ``terminal``): each subprocess has
``_GIT_TIMEOUT``; the engine wall-clock ceiling is
``serial_ops × _GIT_TIMEOUT + _GIT_KILL_SLACK`` so kill/reap never races the
outer ``asyncio.wait_for``. Status uses a single ``git status -sb`` (branch +
porcelain) to keep serial_ops at 2 for the common read path.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
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
    {"status", "diff", "log", "add", "commit", "branch", "checkout", "push"}
)
_WRITE_SUBCOMMANDS = frozenset({"add", "commit", "branch", "checkout", "push"})
_NO_REPO_CODE = "no_repo"


def git_write_subcommands() -> frozenset[str]:
    """Git subcommands that mutate repo state and require user approval on workers."""
    return _WRITE_SUBCOMMANDS


# Hard-ban list lives in ``runtime.safety_breaker`` (P3 unified circuit breaker).
_FORBIDDEN_PATTERNS = git_forbidden_subcommands()
_PROTECTED_BRANCHES = git_protected_branches()
_DIFF_OUTPUT_LIMIT = 16000
_STATUS_LINE_LIMIT = 200
# Per-subprocess ceiling. Engine outer = serial_ops × this + kill slack.
_GIT_TIMEOUT = 20.0
_GIT_KILL_SLACK = 5.0


def git_tool_timeout_seconds(arguments: dict[str, Any] | None = None) -> float:
    """Engine wall-clock ceiling for one ``git`` tool call (must outlive inner ops).

    ``ensure_repo`` + primary command = 2; ``commit`` also probes branch and short SHA;
    ``push``: ensure_repo + remotes + network push (inner push up to 60s) — outer must
    stay above the sum of bounded subprocesses.
    """
    sub = str((arguments or {}).get("subcommand", "")).strip().lower()
    if sub == "push":
        # ensure_repo (~2×20) + remote list (20) + push (60) + slack
        return 2 * _GIT_TIMEOUT + _GIT_TIMEOUT + 60.0 + _GIT_KILL_SLACK
    if sub == "commit":
        serial = 4
    else:
        serial = 2
    return serial * _GIT_TIMEOUT + _GIT_KILL_SLACK


GIT_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subcommand": {
            "type": "string",
            "enum": [
                "status",
                "diff",
                "log",
                "add",
                "commit",
                "branch",
                "checkout",
                "push",
            ],
            "description": (
                "要执行的 git 子命令。前置条件：仅当工作区【根】存在 `.git` 时可用"
                "（不扫嵌套子仓、不上溯父仓、不自动 init）。"
                "探路/摸底优先 file_list / grep；本工具用于分支、diff、log 等 VCS 事实。"
                "只读 status/diff/log：无仓 → success + metadata.code=no_repo；"
                "写入 add/commit/branch/checkout/push：无仓仍硬错。"
                "push 需用户授权；force / 保护分支仍拒；无凭据会失败。"
            ),
        },
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "status/diff/add 的路径过滤（工作区相对路径）。add 时必填。"
                "大仓 status/diff 请尽量收窄 paths，避免全树扫描超时。"
            ),
        },
        "staged": {
            "type": "boolean",
            "description": "diff 时只看暂存区（等同 git diff --cached）。默认 false。",
            "default": False,
        },
        "include_untracked": {
            "type": "boolean",
            "description": (
                "status 是否包含未跟踪文件。默认 false（--untracked-files=no），"
                "大仓更快；需要看未跟踪时显式传 true。"
            ),
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
        "remote": {
            "type": "string",
            "description": (
                "push 的远程名（默认 origin）。仅远程名，禁止 refspec / 选项形态。"
            ),
            "default": "origin",
        },
        "set_upstream": {
            "type": "boolean",
            "description": "push 时设置上游跟踪（--set-upstream）。默认 false。",
            "default": False,
        },
    },
    "required": ["subcommand"],
}


def _error(error: str, start: float, **kwargs: Any) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        success=False,
        output="",
        error=error,
        duration_ms=int((time.monotonic() - start) * 1000),
        **kwargs,
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


def _git_spawn_kwargs() -> dict[str, Any]:
    """POSIX: new session so timeout can ``killpg`` the whole tree (sandbox pattern)."""
    return {} if sys.platform == "win32" else {"start_new_session": True}


async def _reap_git_process(proc: asyncio.subprocess.Process) -> None:
    """Kill the git child and descendants, then reap (best-effort, never raises)."""
    if proc.returncode is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=5.0)


async def _run_git(
    args: list[str], *, cwd: str, timeout: float = _GIT_TIMEOUT
) -> tuple[str, str, int]:
    """Run git command, return (stdout, stderr, exit_code).

    ``GIT_CEILING_DIRECTORIES`` is set to the workspace root so discovery never
    climbs into a parent repo (e.g. workspace nested under the host monorepo).
    On timeout / cancel, reaps the process tree (Windows ``taskkill /T``).
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
        **_git_spawn_kwargs(),
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        await _reap_git_process(proc)
        return "", f"git 操作超时（{' '.join(args)}）", 1
    except asyncio.CancelledError:
        await _reap_git_process(proc)
        raise
    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
        proc.returncode or 0,
    )


async def _git_failure(
    stdout: str, stderr: str, exit_code: int, start: float, **kwargs: Any
) -> ToolResult:
    detail = (stderr or stdout or f"git 退出码 {exit_code}").strip()
    meta = dict(kwargs.pop("metadata", {}) or {})
    if "超时" in detail:
        meta.setdefault("timeout_layer", "inner")
    return _error(detail, start, metadata=meta, **kwargs)


_NO_LOCAL_REPO_MSG = (
    "当前工作区内没有 Git 仓库（仅识别工作区根下的 .git；不会上溯到父目录仓库）"
)


def _no_repo_ok(start: float) -> ToolResult:
    """Read-only no-repo: success with machine-readable code (never fake a clean tree)."""
    return _ok(
        _NO_LOCAL_REPO_MSG,
        start,
        metadata={"code": _NO_REPO_CODE},
    )


async def _ensure_git_repo(
    cwd: str, start: float, *, write: bool
) -> ToolResult | None:
    # Fast path: refuse before any git discovery that could surface a parent repo.
    if not _workspace_has_local_git(cwd):
        if write:
            return _error(_NO_LOCAL_REPO_MSG, start)
        return _no_repo_ok(start)
    stdout, stderr, code = await _run_git(
        ["rev-parse", "--is-inside-work-tree"], cwd=cwd
    )
    if code != 0 or stdout.strip() != "true":
        detail = (stderr or stdout or _NO_LOCAL_REPO_MSG).strip()
        if write:
            return _error(detail, start)
        return _ok(detail, start, metadata={"code": _NO_REPO_CODE})
    return None


async def _current_branch(cwd: str) -> str:
    stdout, _, code = await _run_git(["branch", "--show-current"], cwd=cwd)
    if code != 0:
        return ""
    return stdout.strip()


def _parse_status_sb(stdout: str) -> tuple[str, str]:
    """Parse ``git status -sb`` into (branch_line, body)."""
    lines = stdout.splitlines()
    if not lines:
        return "(无)", ""
    first = lines[0]
    if first.startswith("## "):
        # ``## main...origin/main [ahead 1]`` → branch token before ``...`` / space.
        rest = first[3:].strip()
        branch = rest.split("...", 1)[0].split(" ", 1)[0].strip() or "(无)"
        body = "\n".join(lines[1:]).rstrip()
        return branch, body
    return "(无)", stdout.rstrip()


def _truncate_status_body(body: str) -> tuple[str, bool, int]:
    """Cap status porcelain lines; return (text, truncated, total_lines)."""
    if not body:
        return "", False, 0
    lines = body.splitlines()
    total = len(lines)
    if total <= _STATUS_LINE_LIMIT:
        return body, False, total
    kept = "\n".join(lines[:_STATUS_LINE_LIMIT])
    kept += (
        f"\n…（已截断，共 {total} 行，仅显示前 {_STATUS_LINE_LIMIT} 行；"
        "请用 paths 收窄范围）"
    )
    return kept, True, total


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
                "在工作区内执行 Git 操作。前置：仅工作区根下的 `.git`"
                "（不扫嵌套、不上溯、不自动 init；多数会话通常无 Git）。"
                "探路摸底优先 file_list/grep；本工具补 VCS 事实（分支/diff/log）。"
                "只读：status / diff / log（无仓 → success + metadata.code=no_repo，"
                "禁止当成干净仓；status 默认不含未跟踪文件）。"
                "写入（需用户授权）：add / commit / branch / checkout / push"
                "（无仓仍硬错）。push 需授权；force / 保护分支仍拒；无凭据会失败。"
                "reset / rebase / merge 等危险操作仍硬禁。"
            ),
            parameters=GIT_TOOL_PARAMETERS,
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.NEVER,
            # Dynamic ceiling via resolve_tool_timeout → git_tool_timeout_seconds.
            timeout_seconds=None,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        subcommand = str(arguments.get("subcommand", "")).strip().lower()
        base_meta = {"subcommand": subcommand} if subcommand else {}

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

        repo_err = await _ensure_git_repo(
            cwd, start, write=subcommand in _WRITE_SUBCOMMANDS
        )
        if repo_err is not None:
            if repo_err.metadata is None:
                repo_err.metadata = {}
            repo_err.metadata = {**base_meta, **(repo_err.metadata or {})}
            return repo_err

        paths = _normalize_paths(arguments.get("paths"))

        if subcommand == "status":
            include_untracked = bool(arguments.get("include_untracked", False))
            return await self._cmd_status(
                cwd, paths, start, include_untracked=include_untracked, meta=base_meta
            )
        if subcommand == "diff":
            staged = bool(arguments.get("staged", False))
            return await self._cmd_diff(
                cwd, paths, staged=staged, start=start, meta=base_meta
            )
        if subcommand == "log":
            max_count = int(arguments.get("max_count", 20))
            max_count = max(1, min(max_count, 100))
            oneline = bool(arguments.get("oneline", True))
            return await self._cmd_log(
                cwd,
                paths,
                max_count=max_count,
                oneline=oneline,
                start=start,
                meta=base_meta,
            )
        if subcommand == "add":
            return await self._cmd_add(cwd, paths, start, meta=base_meta)
        if subcommand == "commit":
            message = str(arguments.get("message", "")).strip()
            return await self._cmd_commit(cwd, message, start, meta=base_meta)
        if subcommand == "branch":
            branch = str(arguments.get("branch", "")).strip()
            return await self._cmd_branch(cwd, branch, start, meta=base_meta)
        if subcommand == "checkout":
            branch = str(arguments.get("branch", "")).strip()
            create = bool(arguments.get("create", False))
            return await self._cmd_checkout(
                cwd, branch, create=create, start=start, meta=base_meta
            )
        if subcommand == "push":
            return await self._cmd_push(
                cwd,
                arguments,
                start=start,
                meta=base_meta,
            )

        return _error(f"子命令 '{subcommand}' 不在允许列表中", start)

    async def _cmd_status(
        self,
        cwd: str,
        paths: list[str],
        start: float,
        *,
        include_untracked: bool,
        meta: dict[str, Any],
    ) -> ToolResult:
        # Single subprocess: branch header + porcelain (avoids branch + status serial).
        args = ["status", "-sb"]
        if not include_untracked:
            args.append("--untracked-files=no")
        if paths:
            args.extend(["--", *paths])
        stdout, stderr, code = await _run_git(args, cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start, metadata=meta)
        branch, body = _parse_status_sb(stdout)
        body, truncated, total = _truncate_status_body(body)
        output = f"## 当前分支: {branch}\n"
        output += body if body else "（工作区干净）"
        out_meta = {
            **meta,
            "include_untracked": include_untracked,
            "truncated": truncated,
            "status_lines": total,
        }
        return _ok(output, start, metadata=out_meta)

    async def _cmd_diff(
        self,
        cwd: str,
        paths: list[str],
        *,
        staged: bool,
        start: float,
        meta: dict[str, Any],
    ) -> ToolResult:
        args = ["diff"]
        if staged:
            args.append("--cached")
        if paths:
            args.extend(["--", *paths])
        stdout, stderr, code = await _run_git(args, cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start, metadata=meta)
        output = stdout.rstrip() or "（无差异）"
        if len(output) > _DIFF_OUTPUT_LIMIT:
            output = truncate_head_tail(output, _DIFF_OUTPUT_LIMIT)
        return _ok(
            output, start, output_limit=_DIFF_OUTPUT_LIMIT, metadata=meta
        )

    async def _cmd_log(
        self,
        cwd: str,
        paths: list[str],
        *,
        max_count: int,
        oneline: bool,
        start: float,
        meta: dict[str, Any],
    ) -> ToolResult:
        args = ["log", f"-n{max_count}"]
        if oneline:
            args.append("--oneline")
        if paths:
            args.extend(["--", *paths])
        stdout, stderr, code = await _run_git(args, cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start, metadata=meta)
        lines = [line for line in stdout.splitlines() if line.strip()]
        body = "\n".join(lines) if lines else "（无提交记录）"
        footer = f"\n\n（共 {len(lines)} 条，可用 max_count 调整）"
        return _ok(body + footer, start, metadata=meta)

    async def _cmd_add(
        self, cwd: str, paths: list[str], start: float, *, meta: dict[str, Any]
    ) -> ToolResult:
        path_err = _validate_add_paths(paths, start)
        if path_err is not None:
            return path_err
        args = ["add", "--", *paths]
        stdout, stderr, code = await _run_git(args, cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start, metadata=meta)
        listed = ", ".join(paths)
        detail = (stdout or stderr).strip()
        output = f"已暂存：{listed}"
        if detail:
            output += f"\n{detail}"
        return _ok(output, start, metadata=meta)

    async def _cmd_commit(
        self, cwd: str, message: str, start: float, *, meta: dict[str, Any]
    ) -> ToolResult:
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
            return await _git_failure(stdout, stderr, code, start, metadata=meta)
        sha, _, sha_code = await _run_git(["rev-parse", "--short", "HEAD"], cwd=cwd)
        short_sha = sha.strip() if sha_code == 0 else ""
        output = f"已提交 {short_sha}：{message}" if short_sha else f"已提交：{message}"
        detail = (stdout or stderr).strip()
        if detail:
            output += f"\n{detail}"
        return _ok(output, start, metadata=meta)

    async def _cmd_branch(
        self, cwd: str, branch: str, start: float, *, meta: dict[str, Any]
    ) -> ToolResult:
        if not branch:
            return _error("branch 需要 branch 参数", start)
        if branch.startswith("-"):
            return _error("分支名不能以 '-' 开头（防止被 git 解析为选项）", start)
        stdout, stderr, code = await _run_git(["branch", branch], cwd=cwd)
        if code != 0:
            return await _git_failure(stdout, stderr, code, start, metadata=meta)
        detail = (stdout or stderr).strip()
        output = f"已创建分支 {branch}"
        if detail:
            output += f"\n{detail}"
        return _ok(output, start, metadata=meta)

    async def _cmd_checkout(
        self,
        cwd: str,
        branch: str,
        *,
        create: bool,
        start: float,
        meta: dict[str, Any],
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
            return await _git_failure(stdout, stderr, code, start, metadata=meta)
        action = "已创建并切换到分支" if create else "已切换到分支"
        detail = (stdout or stderr).strip()
        output = f"{action} {branch}"
        if detail:
            output += f"\n{detail}"
        return _ok(output, start, metadata=meta)

    async def _cmd_push(
        self,
        cwd: str,
        arguments: dict[str, Any],
        *,
        start: float,
        meta: dict[str, Any],
    ) -> ToolResult:
        """Push current branch to a named remote — never force, never arbitrary refspec."""
        # Reject smuggled force / refspec keys before any network I/O.
        if any(
            k in arguments
            for k in ("force", "force_with_lease", "forceWithLease", "refspec")
        ):
            return _error(
                "禁止 force push 与自定义 refspec（含 --force / -f / --force-with-lease）；"
                "仅允许将当前功能分支推送到指定 remote",
                start,
            )
        if "branch" in arguments and str(arguments.get("branch") or "").strip():
            # Branch is derived from HEAD; accepting an explicit target would reopen
            # feature:main-style bypasses.
            return _error(
                "push 不接受 branch/refspec 参数：只推送当前分支同名到 remote",
                start,
            )

        remote = str(arguments.get("remote") or "origin").strip() or "origin"
        if remote.startswith("-"):
            return _error("remote 名不能以 '-' 开头（防止被 git 解析为选项）", start)
        if ":" in remote or any(ch.isspace() for ch in remote):
            return _error(
                "remote 仅允许远程名（默认 origin），禁止 refspec 或空白",
                start,
            )
        if remote in {"-f", "--force", "--force-with-lease"}:
            return _error("禁止 force push", start)

        set_upstream = bool(arguments.get("set_upstream", False))

        branch = await _current_branch(cwd)
        if not branch:
            return _error("无法确定当前分支，拒绝 push", start)
        if branch in _PROTECTED_BRANCHES:
            return _error(
                "禁止从 main/master 推送，请先 checkout 到功能分支后再 push",
                start,
            )

        remotes_out, remotes_err, remotes_code = await _run_git(["remote"], cwd=cwd)
        if remotes_code != 0:
            detail = (remotes_err or remotes_out or "无法列出 remote").strip()
            return _error(detail, start)
        remotes = [line.strip() for line in remotes_out.splitlines() if line.strip()]
        if not remotes:
            return _error(
                "当前仓库未配置 remote。请先配置 remote"
                "（如 git remote add origin <url>），"
                "或打开已配置凭据的本地仓库后再 push。",
                start,
            )
        if remote not in remotes:
            listed = ", ".join(remotes)
            return _error(
                f"remote '{remote}' 不存在（已配置：{listed}）。"
                "请先配置 remote，或打开已配置凭据的本地仓库后再 push。",
                start,
            )

        args = ["push"]
        if set_upstream:
            args.append("--set-upstream")
        # Remote name + current branch only — never a src:dst refspec.
        args.extend([remote, branch])
        # Network-bound; keep under engine outer (push serial=4 × 20s).
        stdout, stderr, code = await _run_git(args, cwd=cwd, timeout=60.0)
        if code != 0:
            # Auth / network failures surface honestly (GIT_TERMINAL_PROMPT=0).
            return await _git_failure(stdout, stderr, code, start, metadata=meta)
        detail = (stdout or stderr).strip()
        action = f"已推送 {branch} → {remote}"
        if set_upstream:
            action += "（已设置上游）"
        output = action if not detail else f"{action}\n{detail}"
        return _ok(output, start, metadata={**meta, "remote": remote, "branch": branch})
