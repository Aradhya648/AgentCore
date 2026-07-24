"""Last-line heuristic circuit breaker for catastrophic / sensitive tool calls.

This module is a **defense-in-depth blacklist**, not a security boundary. Patterns
are intentionally narrow and honest: they catch common catastrophic shapes
(``rm -rf /``, force-push to protected branches, raw-device writes, etc.) and
block reads of obvious credential paths. They do **not** intercept every
dangerous command — comments, audit copy, and approval-card hints must not claim
otherwise.

Permission presets (including ``full_trust``), kickoff grants, and turn-wide
「本轮放行」never override these rules. Aligns with Claude Code's practice that
bypass mode still trips the circuit breaker.

Git's hard-forbidden subcommand set lives here as the single source of truth;
``tools.builtin.git_ops`` keeps its boundary behavior by importing that set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

# ── Git hard-ban (unchanged behavior; single source) ─────────────────────────

GIT_FORBIDDEN_SUBCOMMANDS: frozenset[str] = frozenset(
    {"push", "reset", "rebase", "merge", "clean", "stash"}
)
GIT_PROTECTED_BRANCHES: frozenset[str] = frozenset({"main", "master"})


def git_forbidden_subcommands() -> frozenset[str]:
    """Subcommands the git tool hard-rejects (not grantable, not mode-dependent)."""
    return GIT_FORBIDDEN_SUBCOMMANDS


def git_protected_branches() -> frozenset[str]:
    return GIT_PROTECTED_BRANCHES


# ── Verdicts ────────────────────────────────────────────────────────────────


class BreakerVerdict(StrEnum):
    """Outcome of evaluating a tool call against the circuit breaker."""

    FORCE_APPROVAL = "force_approval"
    """Destructive / irreversible shape — always ask a human; grants do not apply."""

    DENY = "deny"
    """Sensitive read (or equivalent) — refuse and steer the model away."""


@dataclass(frozen=True, slots=True)
class BreakerHit:
    verdict: BreakerVerdict
    rule_id: str
    """Stable id for tests / audit (e.g. ``destructive.rm_root``)."""

    reason: str
    """Chinese explanation for humans and model backfill — honest, not absolute."""


# ── Destructive command heuristics ──────────────────────────────────────────
#
# Matched against shell/command/code text. Keep patterns specific so ordinary
# ``rm -rf build/`` or ``git push`` to a feature branch do not trip the breaker.

# Targets that are catastrophic when passed to recursive delete — not ordinary
# workspace paths like ``/tmp/build`` or ``./dist``.
_RM_CATASTROPHIC_TARGET = (
    r"(?:"
    r"/(?:\s|$|[;&|'\"`])"  # bare root ``/``
    r"|/\*(?:\s|$|[;&|'\"`])"  # ``/*``
    r"|~(?:/|\s|$|[;&|'\"`])"  # home
    r"|\$\{?HOME\}?(?:/|\s|$|[;&|'\"`])"
    r"|\%USERPROFILE\%(?:\\|/|\s|$|[;&|'\"`])?"
    r"|[A-Za-z]:\\?(?:\s|$|[;&|'\"`])"  # bare Windows drive root
    r")"
)

_DESTRUCTIVE_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "destructive.rm_root",
        re.compile(
            r"(?i)(?:^|[\s;&|`(])"
            r"(?:sudo\s+)?"
            r"rm\b[^\n;|&]*?"
            r"(?:-rf\b|-fr\b|--recursive\b[^\n;|&]*?--force\b|--force\b[^\n;|&]*?--recursive\b)"
            r"[^\n;|&]*?"
            + _RM_CATASTROPHIC_TARGET
        ),
        "检测到疑似删除根目录/家目录的命令（启发式兜底，并非完整拦截）。需人工确认后才能执行。",
    ),
    (
        "destructive.format_device",
        re.compile(
            r"(?i)(?:^|[\s;&|`(])"
            r"(?:mkfs(?:\.\w+)?\b"
            r"|format\s+[A-Za-z]:"
            r"|diskpart\b"
            r"|dd\b[^\n;|&]*\bof\s*=\s*/dev/"
            r"|\\\\\?\\PhysicalDrive"
            r"|\\\\\.\\PhysicalDrive)"
        ),
        "检测到疑似格式化或写入块设备的命令（启发式兜底，并非完整拦截）。需人工确认后才能执行。",
    ),
    (
        "destructive.git_force_push_protected",
        re.compile(
            r"(?i)git\s+push\b[^\n;|&]*"
            r"(?:--force(?:-with-lease)?\b|(?<![-\w])-f(?![-\w]))"
            r"[^\n;|&]*\b(?:main|master)\b"
            r"|"
            r"git\s+push\b[^\n;|&]*\b(?:main|master)\b[^\n;|&]*"
            r"(?:--force(?:-with-lease)?\b|(?<![-\w])-f(?![-\w]))"
        ),
        "检测到疑似向 main/master 强制推送的命令（启发式兜底，并非完整拦截）。"
        "需人工确认后才能执行。",
    ),
    (
        "destructive.shutdown",
        re.compile(
            r"(?i)(?:^|[\s;&|`(])"
            r"(?:shutdown\b|poweroff\b|reboot\b|halt\b"
            r"|Stop-Computer\b|Restart-Computer\b)"
        ),
        "检测到疑似关机/重启主机的命令（启发式兜底，并非完整拦截）。需人工确认后才能执行。",
    ),
)

# ── Sensitive path heuristics ────────────────────────────────────────────────

_SENSITIVE_BASENAME_EXACT: frozenset[str] = frozenset(
    {
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.test",
        ".env.staging",
        "credentials.json",
        "credentials.yml",
        "credentials.yaml",
        "secrets.json",
        "secrets.yml",
        "secrets.yaml",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa.pub",  # still credential-adjacent; deny read by default
        "id_ed25519.pub",
        "authorized_keys",
        "known_hosts",
        ".npmrc",
        ".pypirc",
        "netrc",
        ".netrc",
        "pgpass",
        ".pgpass",
    }
)

_SENSITIVE_BASENAME_PREFIXES: tuple[str, ...] = (".env.",)
_SENSITIVE_BASENAME_SUFFIXES: tuple[str, ...] = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
)
_SENSITIVE_PATH_SEGMENTS: frozenset[str] = frozenset(
    {".ssh", ".gnupg", ".aws", ".azure", ".gcloud", "private-keys", "private_keys"}
)

_SENSITIVE_DENY_REASON = (
    "该路径疑似包含凭据或密钥类敏感文件，默认拒绝读取（启发式兜底，并非完整拦截）。"
    "请改用用户明示提供的非敏感配置，或请用户在对话中粘贴所需片段。"
)


def is_sensitive_path(path: str) -> bool:
    """True when ``path`` looks like a credential / secret file (heuristic)."""
    raw = (path or "").strip()
    if not raw or raw in {".", "./", ".\\"}:
        return False
    # Normalize separators; PurePosixPath keeps drive letters oddly, so try both.
    candidates = [PurePosixPath(raw.replace("\\", "/"))]
    if "\\" in raw or re.match(r"^[A-Za-z]:", raw):
        candidates.append(PureWindowsPath(raw))
    for p in candidates:
        parts = [part for part in p.parts if part not in {"/", ".", ""}]
        if not parts:
            continue
        for part in parts[:-1]:
            if part.lower() in _SENSITIVE_PATH_SEGMENTS:
                return True
        name = parts[-1]
        if _basename_is_sensitive(name):
            return True
    return False


def _basename_is_sensitive(name: str) -> bool:
    lower = name.lower()
    if lower in _SENSITIVE_BASENAME_EXACT or name in _SENSITIVE_BASENAME_EXACT:
        return True
    if any(lower.startswith(prefix) for prefix in _SENSITIVE_BASENAME_PREFIXES):
        return True
    if any(lower.endswith(suffix) for suffix in _SENSITIVE_BASENAME_SUFFIXES):
        return True
    # Globs that clearly target credential basenames (``.env*``, ``*.pem``).
    if "*" in name or "?" in name:
        approx = re.sub(r"[*?]+", "", name)
        if approx and _basename_is_sensitive(approx):
            return True
        if lower.startswith(".env") or lower.endswith(".env") or ".env." in lower:
            return True
    return False


def scan_destructive_text(text: str) -> BreakerHit | None:
    """Scan free-form command/code text for catastrophic patterns."""
    if not text or not text.strip():
        return None
    for rule_id, pattern, reason in _DESTRUCTIVE_RULES:
        if pattern.search(text):
            return BreakerHit(
                verdict=BreakerVerdict.FORCE_APPROVAL,
                rule_id=rule_id,
                reason=reason,
            )
    return None


def _command_text_for_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name == "terminal":
        return str(arguments.get("command") or "")
    if tool_name == "code_execute":
        return str(arguments.get("code") or "")
    if tool_name == "test_run":
        # Whitelisted argv builder; still scan filter + any leaked command fields.
        parts = [
            str(arguments.get("filter") or ""),
            str(arguments.get("command") or ""),
            str(arguments.get("code") or ""),
        ]
        return "\n".join(p for p in parts if p)
    if tool_name == "git":
        # Extra surface if shell wrappers somehow call through — primary ban is
        # still the allowed-subcommand list in git_ops.
        sub = str(arguments.get("subcommand") or "").strip().lower()
        branch = str(arguments.get("branch") or "")
        return f"git {sub} {branch}".strip()
    return ""


def _path_args_for_tool(tool_name: str, arguments: dict[str, Any]) -> list[str]:
    if tool_name == "file_read":
        return [str(arguments.get("path") or "")]
    if tool_name == "grep":
        paths = [str(arguments.get("path") or "")]
        glob = str(arguments.get("glob") or "").strip()
        if glob:
            paths.append(glob)
        return paths
    if tool_name == "code_search":
        return [str(arguments.get("path_prefix") or "")]
    return []


def evaluate_tool_call(tool_name: str, arguments: dict[str, Any] | None) -> BreakerHit | None:
    """Evaluate a tool call; return a hit when the circuit breaker should intervene.

    Returns ``None`` when the call is not matched (normal approval / execution path).
    """
    args = arguments or {}
    name = (tool_name or "").strip()

    # Sensitive reads first (deny — never escalate to approval).
    if name in {"file_read", "grep", "code_search"}:
        for path in _path_args_for_tool(name, args):
            if is_sensitive_path(path):
                return BreakerHit(
                    verdict=BreakerVerdict.DENY,
                    rule_id="sensitive.path_read",
                    reason=_SENSITIVE_DENY_REASON,
                )

    # Git hard-ban at the breaker layer (git_ops still enforces at execute).
    if name == "git":
        sub = str(args.get("subcommand") or "").strip().lower()
        if sub in GIT_FORBIDDEN_SUBCOMMANDS or any(
            pat in sub for pat in GIT_FORBIDDEN_SUBCOMMANDS
        ):
            return BreakerHit(
                verdict=BreakerVerdict.DENY,
                rule_id="git.forbidden_subcommand",
                reason=(
                    f"Git 子命令 '{sub}' 被硬禁清单拒绝（push/reset/rebase 等不可由"
                    "权限模式或本轮放行放开）。请改由用户在本机终端手动完成。"
                ),
            )

    # Destructive text on execution / terminal surfaces.
    if name in {"terminal", "code_execute", "test_run"}:
        if name == "terminal":
            sub = str(args.get("subcommand") or "").strip().lower()
            if sub and sub != "start":
                return None
        hit = scan_destructive_text(_command_text_for_tool(name, args))
        if hit is not None:
            return hit

    return None
