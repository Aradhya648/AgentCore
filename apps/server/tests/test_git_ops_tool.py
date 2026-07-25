"""Regression tests for GitTool safety guards (``tools/builtin/git_ops.py``).

Pins the write-path hard rejects that catalog/approval tests do not cover:
forbidden subcommands, protected-branch commits, add-path policy, CEO write ban,
and branch/checkout argument handling. Hermetic: throwaway repos under ``tmp_path``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agentcore.tools.builtin.git_ops import (
    _ALLOWED_SUBCOMMANDS,
    _FORBIDDEN_PATTERNS,
    _PROTECTED_BRANCHES,
    GitTool,
    _validate_add_paths,
    git_write_subcommands,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from agentcore.workspace.write_claims import WriteCoordinator

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")

_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=_GIT_ENV,
    )


def _init_repo(path: Path, *, branch: str = "feature/work") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(path, "init", "-b", branch)
    _run_git(path, "config", "user.email", "tester@example.com")
    _run_git(path, "config", "user.name", "Tester")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(path, "add", "README.md")
    _run_git(path, "commit", "-m", "init")
    return path


def _ceo_ctx(workspace: Path) -> ToolContext:
    """CEO path: no worker-only coordination channels."""
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="ceo",
        backend=ServerWorkspace(root=workspace, sandbox=SubprocessSandbox()),
        user_id="u",
    )


def _worker_ctx(workspace: Path) -> ToolContext:
    """Worker path: any coordination channel present clears the CEO write ban."""
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="worker",
        backend=ServerWorkspace(root=workspace, sandbox=SubprocessSandbox()),
        user_id="u",
        write_coordinator=WriteCoordinator(),
    )


# --- allowlist / forbidden patterns ---


def test_forbidden_patterns_disjoint_from_allowlist():
    # Defense-in-depth: every hard-banned verb must stay outside the allowlist so a
    # future allowlist expansion cannot silently re-enable push/reset/….
    assert _FORBIDDEN_PATTERNS.isdisjoint(_ALLOWED_SUBCOMMANDS)
    assert {"push", "reset", "rebase", "merge", "clean", "stash"} <= _FORBIDDEN_PATTERNS


@pytest.mark.parametrize("subcommand", sorted(_FORBIDDEN_PATTERNS))
async def test_forbidden_subcommands_are_rejected(tmp_path: Path, subcommand: str):
    result = await GitTool().execute({"subcommand": subcommand}, _ceo_ctx(tmp_path))
    assert result.success is False
    assert result.error
    # Allowlist rejects first today; forbidden-pattern message is the defense-in-depth
    # wording if a name ever lands in both sets. Either path must refuse.
    assert (
        "不在允许列表中" in result.error
        or "被安全策略拒绝" in result.error
    )


async def test_unknown_subcommand_rejected(tmp_path: Path):
    result = await GitTool().execute({"subcommand": "reflog"}, _ceo_ctx(tmp_path))
    assert result.success is False
    assert "不在允许列表中" in (result.error or "")


# --- CEO write ban ---


@pytest.mark.parametrize("subcommand", sorted(git_write_subcommands()))
async def test_ceo_context_rejects_all_write_subcommands(tmp_path: Path, subcommand: str):
    _init_repo(tmp_path / "repo")
    args: dict[str, Any] = {"subcommand": subcommand}
    if subcommand == "add":
        args["paths"] = ["README.md"]
    elif subcommand == "commit":
        args["message"] = "x"
    elif subcommand in ("branch", "checkout"):
        args["branch"] = "other"
    result = await GitTool().execute(args, _ceo_ctx(tmp_path / "repo"))
    assert result.success is False
    assert "delegate" in (result.error or "").lower() or "Worker" in (result.error or "")


async def test_ceo_context_allows_read_status(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    result = await GitTool().execute({"subcommand": "status"}, _ceo_ctx(repo))
    assert result.success is True
    assert "当前分支" in result.output


async def test_status_refuses_parent_repo_when_workspace_has_no_git(tmp_path: Path):
    """Workspace nested under a parent git tree must not operate the parent repo.

    Reproduces host-path leak class: data_dir / scratch lives under the monorepo
    (e.g. ``C:/Project/...``); without a ceiling, ``git status`` would climb out.
    """
    parent = _init_repo(tmp_path / "parent", branch="feature/parent")
    nested = parent / "nested_workspace"
    nested.mkdir()
    (nested / "notes.txt").write_text("scratch only\n", encoding="utf-8")
    assert not (nested / ".git").exists()

    # Sanity: plain git *would* see the parent work tree from nested cwd.
    climbed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=nested,
        check=True,
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )
    assert Path(climbed.stdout.strip()).resolve() == parent.resolve()

    result = await GitTool().execute({"subcommand": "status"}, _ceo_ctx(nested))
    assert result.success is False
    assert result.error
    assert "没有 Git 仓库" in result.error or "不会上溯" in result.error
    # Must not echo parent branch / status as if nested were the repo.
    assert "feature/parent" not in (result.output or "")
    assert "当前分支" not in (result.output or "")


async def test_status_uses_workspace_repo_not_parent(tmp_path: Path):
    """When the workspace has its own ``.git``, operate that repo — not a parent."""
    parent = _init_repo(tmp_path / "parent", branch="feature/parent")
    nested = _init_repo(parent / "nested_repo", branch="feature/nested")
    result = await GitTool().execute({"subcommand": "status"}, _ceo_ctx(nested))
    assert result.success is True
    assert "feature/nested" in result.output
    assert "feature/parent" not in result.output


async def test_no_git_anywhere_reports_clear_error(tmp_path: Path):
    bare = tmp_path / "not_a_repo"
    bare.mkdir()
    result = await GitTool().execute({"subcommand": "status"}, _ceo_ctx(bare))
    assert result.success is False
    assert "没有 Git 仓库" in (result.error or "")


# --- add path policy ---


@pytest.mark.parametrize(
    "paths,needle",
    [
        ([], "显式 paths"),
        (["."], "禁止 add 路径"),
        (["-A"], "禁止 add 路径"),
        (["--all"], "禁止 add 路径"),
        (["src/*.py"], "通配符"),
        (["foo?.txt"], "通配符"),
        ([""], "空路径"),
    ],
)
def test_validate_add_paths_rejects_dangerous_inputs(paths: list[str], needle: str):
    err = _validate_add_paths(paths, start=0.0)
    assert err is not None
    assert err.success is False
    assert needle in (err.error or "")


def test_validate_add_paths_accepts_explicit_files():
    assert _validate_add_paths(["src/a.py", "docs/readme.md"], start=0.0) is None


async def test_add_rejects_dot_via_execute(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    result = await GitTool().execute(
        {"subcommand": "add", "paths": ["."]},
        _worker_ctx(repo),
    )
    assert result.success is False
    assert "禁止 add" in (result.error or "")


# --- protected branches ---


@pytest.mark.parametrize("branch", sorted(_PROTECTED_BRANCHES))
async def test_commit_on_protected_branch_rejected(tmp_path: Path, branch: str):
    repo = _init_repo(tmp_path / "repo", branch=branch)
    (repo / "extra.txt").write_text("x\n", encoding="utf-8")
    _run_git(repo, "add", "extra.txt")
    result = await GitTool().execute(
        {"subcommand": "commit", "message": "should not land"},
        _worker_ctx(repo),
    )
    assert result.success is False
    assert "main/master" in (result.error or "")
    # Working tree still has the staged file — commit did not happen.
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )
    assert "extra.txt" in status.stdout


async def test_commit_on_feature_branch_allowed(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo", branch="feature/ok")
    (repo / "extra.txt").write_text("x\n", encoding="utf-8")
    result = await GitTool().execute(
        {"subcommand": "add", "paths": ["extra.txt"]},
        _worker_ctx(repo),
    )
    assert result.success is True
    result = await GitTool().execute(
        {"subcommand": "commit", "message": "add extra"},
        _worker_ctx(repo),
    )
    assert result.success is True
    assert "已提交" in result.output


# --- branch / checkout args ---


async def test_branch_requires_branch_name(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    result = await GitTool().execute({"subcommand": "branch"}, _worker_ctx(repo))
    assert result.success is False
    assert "branch 需要 branch 参数" in (result.error or "")


async def test_checkout_requires_branch_name(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    result = await GitTool().execute({"subcommand": "checkout"}, _worker_ctx(repo))
    assert result.success is False
    assert "checkout 需要 branch 参数" in (result.error or "")


@pytest.mark.parametrize("branch", ["-f", "--force", "-D"])
async def test_branch_rejects_option_like_names(tmp_path: Path, branch: str):
    # audit 05 P3-1: a ``-``-prefixed branch would be parsed by git as an option
    # (e.g. ``branch -f``); reject before it ever reaches argv.
    repo = _init_repo(tmp_path / "repo")
    result = await GitTool().execute(
        {"subcommand": "branch", "branch": branch},
        _worker_ctx(repo),
    )
    assert result.success is False
    assert "'-' 开头" in (result.error or "")


@pytest.mark.parametrize("branch", ["-f", "--force", "-D"])
async def test_checkout_rejects_option_like_names(tmp_path: Path, branch: str):
    repo = _init_repo(tmp_path / "repo")
    result = await GitTool().execute(
        {"subcommand": "checkout", "branch": branch},
        _worker_ctx(repo),
    )
    assert result.success is False
    assert "'-' 开头" in (result.error or "")


async def test_branch_creates_named_branch(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    result = await GitTool().execute(
        {"subcommand": "branch", "branch": "feature/new"},
        _worker_ctx(repo),
    )
    assert result.success is True
    assert "已创建分支 feature/new" in result.output
    branches = subprocess.run(
        ["git", "branch", "--list", "feature/new"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )
    assert "feature/new" in branches.stdout


async def test_checkout_create_switches_to_new_branch(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo", branch="feature/base")
    result = await GitTool().execute(
        {"subcommand": "checkout", "branch": "feature/created", "create": True},
        _worker_ctx(repo),
    )
    assert result.success is True
    assert "已创建并切换到分支 feature/created" in result.output
    current = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )
    assert current.stdout.strip() == "feature/created"


async def test_checkout_switches_existing_branch(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo", branch="feature/a")
    _run_git(repo, "branch", "feature/b")
    result = await GitTool().execute(
        {"subcommand": "checkout", "branch": "feature/b"},
        _worker_ctx(repo),
    )
    assert result.success is True
    assert "已切换到分支 feature/b" in result.output
    current = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )
    assert current.stdout.strip() == "feature/b"


async def test_commit_requires_message(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    result = await GitTool().execute({"subcommand": "commit"}, _worker_ctx(repo))
    assert result.success is False
    assert "message" in (result.error or "")
