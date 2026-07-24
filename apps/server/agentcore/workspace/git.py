"""Clone a public git repository into a conversation's workspace (决策⑤).

The developer half of "文件进出": after upload (anyone), ``git clone`` brings an
existing public repo into the project space. Cloud mode runs ``git`` as a server
subprocess into the resolved workspace root; P2 (local mode) routes the same
operation through the desktop channel — this module is the server-side seam.

Safety:
- ``git`` is invoked via argv (``create_subprocess_exec``) — never a shell
  string — so a hostile URL cannot inject commands.
- Only ``http(s)`` URLs are accepted (public repos; private-repo tokens come
  later). ``ssh``/``file``/etc. are rejected so the server can't be coerced into
  reading local repos or arbitrary hosts via a different transport.
- The URL is run through the shared SSRF guard (``core.net.classify_url``, the same
  policy as ``read_url`` / favicon), so a clone target that resolves to a
  local/internal/reserved address (e.g. ``169.254.169.254``) is refused (SEC-006).
- The clone is shallow + single-branch, has a timeout, and runs with
  ``GIT_TERMINAL_PROMPT=0`` so an auth-required repo fails fast instead of
  hanging on a credential prompt.
- The destination is resolved through the traversal guard, so it can never land
  outside the workspace, and an existing non-empty destination is refused.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

from agentcore.config import settings
from agentcore.core.net import PRIVATE_IP_BLOCKS, URLBlock, classify_url
from agentcore.workspace._paths import resolve_safe_path
from agentcore.workspace.locate import resolve_workspace_root

_ALLOWED_SCHEMES = ("http", "https")


class CloneError(Exception):
    """The ``git clone`` subprocess failed (bad URL, missing repo, network, …)."""


def _validate_url(repo_url: str) -> None:
    parsed = urlparse(repo_url.strip())
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError("仅支持 http(s) 协议的仓库地址")
    if not parsed.netloc:
        raise ValueError("仓库地址无效")


async def _reject_ssrf(repo_url: str) -> None:
    """Block a clone target that resolves to a local/internal/reserved address.

    ``git clone`` makes the server an HTTP client to ``repo_url``; without this it
    would be an SSRF hole (clone ``http://169.254.169.254/…`` or an intranet host)
    that bypasses the same private-IP guard ``read_url`` / the favicon proxy already
    apply (SEC-006). Reuses the single shared definition (``core.net``) so there is
    one SSRF policy.

    Scope is only the *address* check: scheme policy is :func:`_validate_url`'s job
    (it runs first, so only http(s) URLs reach here). A DNS failure is left to
    ``git`` itself, so a transient lookup miss surfaces as an honest network error
    rather than a misleading SSRF refusal.
    """
    block = await classify_url(repo_url)
    if block in (URLBlock.BLOCKED_HOST, *PRIVATE_IP_BLOCKS):
        raise ValueError("仓库地址被拒：不可指向本地 / 内网 / 保留地址")


def _derive_dest_name(repo_url: str) -> str:
    """The default target dir: the repo's name (last path segment, minus .git)."""
    path = urlparse(repo_url.strip()).path.rstrip("/")
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repo"


async def clone_repo(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    repo_url: str,
    dest: str | None = None,
    depth: int = 1,
) -> str:
    """Clone ``repo_url`` into the conversation's workspace; return the dest path.

    ``dest`` (workspace-relative) defaults to the repo name. Raises ``ValueError``
    for a bad URL / destination, ``CloneError`` if the clone itself fails.
    """
    _validate_url(repo_url)
    await _reject_ssrf(repo_url)
    root = resolve_workspace_root(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    dest_rel = dest.strip() if dest and dest.strip() else _derive_dest_name(repo_url)
    target = resolve_safe_path(root, dest_rel)
    if target is None:
        raise ValueError("目标路径无效")
    if target.exists() and any(target.iterdir()):
        raise ValueError("目标目录已存在且非空")

    await _git_clone(
        repo_url, target, depth=depth, timeout=settings.workspace_clone_timeout_seconds
    )
    # ``target`` is the resolved absolute path from the traversal guard; report it
    # back relative to the (resolved) workspace root for the client.
    return target.relative_to(root.resolve()).as_posix()


async def _git_clone(repo_url: str, dest: Path, *, depth: int, timeout: int) -> None:
    """Run ``git clone`` into ``dest`` via argv (no shell); raise on failure.

    Separated from :func:`clone_repo` (which owns URL policy) so the raw mechanics
    can be tested hermetically against a local ``file://`` source repo.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["git", "clone", "--single-branch"]
    if depth and depth > 0:
        args += ["--depth", str(depth)]
    args += [repo_url, str(dest)]

    # Never prompt for credentials: a private/auth-required repo should fail fast,
    # not hang the request waiting on stdin that will never come.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except OSError as e:  # git not installed / not on PATH
        raise CloneError(f"无法启动 git：{e}") from e

    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise CloneError(f"git clone 超时（{timeout} 秒）") from None

    if proc.returncode != 0:
        detail = stderr.decode(errors="replace").strip() or "git clone 失败"
        raise CloneError(detail)
