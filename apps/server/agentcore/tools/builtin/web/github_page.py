"""GitHub HTML page → api.github.com fast path for ``read_url``.

``github.com/{owner}/{repo}`` (root / tree / blob) often times out or returns
login chrome over HTML; the REST API is smaller and exposes ``private`` /
``visibility`` so the model need not guess. Match failure or any API error
returns ``None`` so the caller falls back to the existing HTML fetch.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from agentcore.core.logging import get_logger

logger = get_logger(__name__)

_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
# First path segment that is never a user/org owning a repo page we care about.
_RESERVED_OWNERS = frozenset(
    {
        "settings",
        "login",
        "logout",
        "join",
        "signup",
        "session",
        "sessions",
        "marketplace",
        "explore",
        "topics",
        "collections",
        "events",
        "sponsors",
        "about",
        "pricing",
        "enterprise",
        "features",
        "security",
        "orgs",
        "organizations",
        "account",
        "notifications",
        "pulls",
        "issues",
        "codespaces",
        "copilot",
        "search",
        "new",
        "dashboard",
        "apps",
        "integrations",
        "site",
        "git-receive-pack",
        "git-upload-pack",
    }
)


@dataclass(frozen=True, slots=True)
class _GithubRepoPage:
    owner: str
    repo: str
    ref: str | None = None  # None → default branch (README API)


@dataclass(frozen=True, slots=True)
class _GithubBlobPage:
    owner: str
    repo: str
    ref: str
    path: str


GithubPage = _GithubRepoPage | _GithubBlobPage


def parse_github_page_url(url: str) -> GithubPage | None:
    """Parse ``github.com/{owner}/{repo}`` root / tree / blob URLs.

    Returns ``None`` for non-GitHub hosts, non-repo pages (issues/PRs/…), or
    malformed paths — caller should use the HTML path.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in _GITHUB_HOSTS:
        return None
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if owner.lower() in _RESERVED_OWNERS:
        return None
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not repo:
        return None

    if len(parts) == 2:
        return _GithubRepoPage(owner=owner, repo=repo)

    kind = parts[2].lower()
    if kind == "tree":
        ref = parts[3] if len(parts) >= 4 else None
        return _GithubRepoPage(owner=owner, repo=repo, ref=ref)
    if kind == "blob":
        if len(parts) < 5:
            return None
        return _GithubBlobPage(
            owner=owner,
            repo=repo,
            ref=parts[3],
            path="/".join(parts[4:]),
        )
    return None


def _api_headers() -> dict[str, str]:
    return {
        "User-Agent": "AgentCore/1.0 (+https://agentcore.dev)",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _decode_github_content(payload: dict[str, Any]) -> str | None:
    """Decode a contents/readme API body; ``None`` if missing or not base64 text."""
    encoding = (payload.get("encoding") or "").lower()
    content = payload.get("content")
    if encoding != "base64" or not isinstance(content, str) or not content.strip():
        return None
    try:
        raw = base64.b64decode(content, validate=False)
    except Exception:
        return None
    return raw.decode("utf-8", errors="replace")


def _format_repo_body(
    meta: dict[str, Any],
    *,
    readme_text: str | None,
    readme_path: str | None,
    max_chars: int,
) -> str:
    owner = meta.get("owner")
    owner_login = owner.get("login", "") if isinstance(owner, dict) else ""
    full_name = meta.get("full_name") or f"{owner_login}/{meta.get('name', '')}"
    visibility = meta.get("visibility") or (
        "private" if meta.get("private") else "public"
    )
    lines = [
        f"repository: {full_name}",
        f"private: {json.dumps(bool(meta.get('private')))}",
        f"visibility: {visibility}",
        f"default_branch: {meta.get('default_branch') or ''}",
    ]
    desc = (meta.get("description") or "").strip()
    if desc:
        lines.append(f"description: {desc}")
    if meta.get("archived"):
        lines.append("archived: true")
    if meta.get("fork"):
        lines.append("fork: true")
    if meta.get("html_url"):
        lines.append(f"html_url: {meta['html_url']}")
    body = "\n".join(lines)
    if readme_text is not None:
        label = readme_path or "README"
        body = f"{body}\n\n--- {label} ---\n{readme_text}"
    return body[:max_chars]


def _format_blob_body(
    *,
    owner: str,
    repo: str,
    ref: str,
    path: str,
    file_text: str,
    max_chars: int,
) -> str:
    header = "\n".join(
        [
            f"repository: {owner}/{repo}",
            f"ref: {ref}",
            f"path: {path}",
        ]
    )
    return f"{header}\n\n--- file ---\n{file_text}"[:max_chars]


async def try_fetch_github_page(
    client: httpx.AsyncClient,
    url: str,
    max_chars: int,
    *,
    safe_request: Any,
) -> tuple[str, str, str] | None:
    """Fetch via api.github.com when ``url`` is a repo/tree/blob page.

    Returns ``(title, text, description)`` on success, else ``None`` (fall back
    to HTML). ``safe_request`` is ``read_url._safe_request`` (SSRF + breaker).
    """
    page = parse_github_page_url(url)
    if page is None:
        return None
    headers = _api_headers()
    try:
        if isinstance(page, _GithubBlobPage):
            return await _fetch_blob(client, page, max_chars, safe_request, headers)
        return await _fetch_repo(client, page, max_chars, safe_request, headers)
    except Exception as e:
        logger.info(
            "tool.read_url_github_api_fallback",
            url=url[:200],
            error=type(e).__name__,
            detail=str(e)[:200],
        )
        return None


async def _fetch_repo(
    client: httpx.AsyncClient,
    page: _GithubRepoPage,
    max_chars: int,
    safe_request: Any,
    headers: dict[str, str],
) -> tuple[str, str, str] | None:
    meta_url = f"https://api.github.com/repos/{quote(page.owner)}/{quote(page.repo)}"
    resp = await safe_request(client, "GET", meta_url, headers=headers)
    if resp.status_code != 200:
        return None
    meta = resp.json()
    if not isinstance(meta, dict):
        return None

    readme_text: str | None = None
    readme_path: str | None = None
    readme_url = f"{meta_url}/readme"
    if page.ref:
        readme_url = f"{readme_url}?ref={quote(page.ref)}"
    readme_resp = await safe_request(client, "GET", readme_url, headers=headers)
    if readme_resp.status_code == 200:
        readme_payload = readme_resp.json()
        if isinstance(readme_payload, dict):
            decoded = _decode_github_content(readme_payload)
            if decoded is not None:
                readme_text = decoded
                path = readme_payload.get("path")
                readme_path = path if isinstance(path, str) else None

    full_name = meta.get("full_name") or f"{page.owner}/{page.repo}"
    title = str(full_name)
    text = _format_repo_body(
        meta, readme_text=readme_text, readme_path=readme_path, max_chars=max_chars
    )
    description = (meta.get("description") or "").strip()
    return title, text, description


async def _fetch_blob(
    client: httpx.AsyncClient,
    page: _GithubBlobPage,
    max_chars: int,
    safe_request: Any,
    headers: dict[str, str],
) -> tuple[str, str, str] | None:
    # Encode path segments but keep slashes (contents API uses path with /).
    enc_path = "/".join(quote(seg) for seg in page.path.split("/"))
    contents_url = (
        f"https://api.github.com/repos/{quote(page.owner)}/{quote(page.repo)}"
        f"/contents/{enc_path}?ref={quote(page.ref)}"
    )
    resp = await safe_request(client, "GET", contents_url, headers=headers)
    if resp.status_code != 200:
        return None
    payload = resp.json()
    # Directory listing is a list — not a file blob; fall back to HTML.
    if not isinstance(payload, dict):
        return None
    if payload.get("type") == "dir" or "content" not in payload:
        return None
    decoded = _decode_github_content(payload)
    if decoded is None:
        return None
    title = f"{page.owner}/{page.repo}/{page.path}"
    text = _format_blob_body(
        owner=page.owner,
        repo=page.repo,
        ref=page.ref,
        path=page.path,
        file_text=decoded,
        max_chars=max_chars,
    )
    # Lead of the file for citation snippet.
    description = re.sub(r"\s+", " ", decoded).strip()[:200]
    return title, text, description
