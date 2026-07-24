"""File operations tools (read, write, list, precise str_replace edit, delete,
move, copy, mkdir, batch).

Thin shells over ``ToolContext.backend``: each tool parses arguments, calls the
workspace backend, maps typed ``WorkspaceError`` failures back to user-facing
messages, and renders a ``ToolResult``. All actual I/O and the path-traversal
guard live in the backend, so the same tools run unchanged against a server or a
local (desktop) workspace.
"""

import re
import time
from posixpath import basename
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_BOTH,
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)
from agentcore.workspace._paths import is_ai_noise_file_name
from agentcore.workspace.protocol import (
    AlreadyExists,
    AmbiguousMatch,
    DirEntry,
    NoMatch,
    NotADirectory,
    NotAFile,
    NotUTF8,
    OutsideWorkspace,
    PathNotFound,
    TreeEntry,
    WorkspaceError,
)

logger = get_logger(__name__)

_DEFAULT_READ_LINES = 500

# Overwrite integrity nudge (soft only — never blocks write / never auto-redispatches).
# Fires when ``file_write`` clobbers a non-empty file and the new body looks truncated
# (omission markers or severe shrink). Same principle as ``engine.audit_gate_nudge``.
_INTEGRITY_SHRINK_RATIO = 0.6
_OMISSION_LITERALS = (
    "中间省略",
    "已保留首尾",
    "（略）",
    "[略]",
)
_OMISSION_RE = re.compile(
    r"(?:\.\.\.|…)\s*omitted|truncated\s+for\s+brevity",
    re.IGNORECASE,
)

# Soft length nudge on oversized ``file_write`` content (never blocks).
# ≈2000 tokens at the project-wide 4 chars/token estimate — catches whole-site HTML /
# long-doc dumps (accident: ~8–9k token single write) without hard-rejecting medium files.
_CHARS_PER_TOKEN_EST = 4
_WRITE_LENGTH_WARN_TOKENS = 2000
_WRITE_LENGTH_WARN_CHARS = _WRITE_LENGTH_WARN_TOKENS * _CHARS_PER_TOKEN_EST

# Hard reject: clobbering an existing substantial file via whole-file overwrite.
# Skeleton+append and tiny stubs stay allowed; threshold is "成篇" not "non-empty".
_SUBSTANTIAL_FILE_CHARS = 400


def is_substantial_existing_body(content: str) -> bool:
    """True when ``content`` looks like a finished article / page worth protecting."""
    return len((content or "").strip()) >= _SUBSTANTIAL_FILE_CHARS


def substantial_overwrite_rejection(path: str, old_chars: int) -> str:
    """User-facing error when ``file_write`` would clobber a substantial file."""
    return (
        f"拒绝整文件覆盖：`{path}` 已是成篇成品（约 {old_chars} 字，阈值 "
        f"{_SUBSTANTIAL_FILE_CHARS} 字）。请改用 str_replace 局部修订，或 "
        "file_append 追加；确需整体换稿时先说明并拆成局部补丁。"
        "新建空文件骨架 + 分段 append 不受影响。"
    )


def substantial_delete_rejection(path: str, old_chars: int) -> str:
    """User-facing error when ``file_delete`` would wipe a substantial draft."""
    return (
        f"拒绝删除成篇草稿：`{path}` 已有约 {old_chars} 字（阈值 "
        f"{_SUBSTANTIAL_FILE_CHARS} 字）。禁止整篇 delete 后重写长文——"
        "请用 str_replace 局部修订，或 file_append 按章续写；"
        "预算不够时停在完整章边界并诚实交接，勿推倒重来。"
    )


def has_omission_marker(content: str) -> bool:
    """True when ``content`` contains a known lazy-elision / truncation marker."""
    if not content:
        return False
    if any(m in content for m in _OMISSION_LITERALS):
        return True
    return _OMISSION_RE.search(content) is not None


def is_severe_shrink(old_chars: int, new_chars: int) -> bool:
    """True when new length is below ``_INTEGRITY_SHRINK_RATIO`` of the old length."""
    return old_chars > 0 and new_chars < old_chars * _INTEGRITY_SHRINK_RATIO


def integrity_nudge_text(
    *,
    path: str,
    reasons: list[str],
    old_chars: int,
    new_chars: int,
) -> str:
    """Soft warning appended to a successful ``file_write`` receipt."""
    reason = "；".join(reasons)
    return (
        f"\n\n[系统提示] 产物疑似不完整（`{path}`：{reason}；"
        f"旧 {old_chars} 字 → 新 {new_chars} 字）。"
        "请检查后用 str_replace / file_append 补全，或向主管说明需重派。"
        "系统只提示、绝不代派、绝不自动重跑、绝不拦截本次写入。"
    )


def overwrite_integrity_nudge(
    path: str, old_content: str, new_content: str
) -> str | None:
    """Return a soft nudge when overwriting a non-empty file looks truncated.

    Only for existing non-empty targets. Never raises; callers append to tool output.
    """
    if not old_content:
        return None
    old_chars = len(old_content)
    new_chars = len(new_content)
    reasons: list[str] = []
    if has_omission_marker(new_content):
        reasons.append("正文含省略标记")
    if is_severe_shrink(old_chars, new_chars):
        reasons.append(f"字数骤降至旧稿 {int(_INTEGRITY_SHRINK_RATIO * 100)}% 以下")
    if not reasons:
        return None
    return integrity_nudge_text(
        path=path, reasons=reasons, old_chars=old_chars, new_chars=new_chars
    )


def is_oversized_write(content: str) -> bool:
    """True when ``content`` meets/exceeds the soft length-warn threshold."""
    return len(content) >= _WRITE_LENGTH_WARN_CHARS


def length_nudge_text(*, path: str, chars: int) -> str:
    """Soft warning appended when a successful ``file_write`` body is oversized."""
    approx_tokens = max(1, chars // _CHARS_PER_TOKEN_EST)
    return (
        f"\n\n[系统提示] 本次 file_write 内容较长（`{path}`：约 {approx_tokens} token / "
        f"{chars} 字，阈值 ≈{_WRITE_LENGTH_WARN_TOKENS} token / "
        f"{_WRITE_LENGTH_WARN_CHARS} 字）。"
        "大产物请改用「骨架 file_write + 分段 file_append」：先写结构/首段，再逐节追加；"
        "不要指望单次 file_write 一口气写完全文。"
        "系统只提示、绝不拦截本次写入。"
    )


def _mark_landed_files(context: ToolContext) -> None:
    """Stamp that this run has written at least one file (handoff empty-body gate)."""
    context.has_landed_files = True


def write_length_nudge(path: str, content: str) -> str | None:
    """Return a soft length nudge for oversized ``file_write`` content, else None."""
    if not is_oversized_write(content):
        return None
    return length_nudge_text(path=path, chars=len(content))


def _truncate_content_lines(content: str, max_lines: int) -> str:
    """Keep the first ``max_lines`` logical lines, preserving original line endings."""
    if max_lines <= 0:
        return ""
    count = 0
    i = 0
    n = len(content)
    while i < n and count < max_lines:
        count += 1
        j = content.find("\n", i)
        if j == -1:
            return content
        i = j + 1
    return content[:i]


def _format_numbered_lines(lines: list[str], start_line: int) -> str:
    return "\n".join(
        f"{lineno:>6}|{text}"
        for lineno, text in zip(
            range(start_line, start_line + len(lines)), lines, strict=True
        )
    )


# 写类工具「回显结果」：worker 写 / 追加 / 替换后，常会为「确认写对没」再花一整轮 read 回读自检
# （trace 4d715ea0 实测：8 个 append worker 全是 读→追加→回读→handoff，那一轮回读零信息增量）。
# 行业实践是让写类工具直接把「改动后的结果」回显进回执（Aider / Cursor / Claude Code 均回 diff /
# 结果片段），使验证在同一轮内完成、免掉那一轮回读。
# 回显有界（行数 + 字符双上限），大文件不炸 token。
_APPEND_ECHO_LINES = 12
_APPEND_ECHO_CHARS = 600
_EDIT_ECHO_CONTEXT = 3
_EDIT_ECHO_MAX_LINES = 24


def _tail_preview(content: str, *, max_lines: int, max_chars: int) -> str:
    """Last ``max_lines`` lines of ``content``, capped at ``max_chars`` (kept from the tail)."""
    lines = content.splitlines()
    tail = "\n".join(lines[-max_lines:])
    elided = len(lines) > max_lines
    if len(tail) > max_chars:
        tail = tail[-max_chars:]
        elided = True
    return ("…\n" if elided else "") + tail


class _TreeNode:
    __slots__ = ("children", "is_dir", "name")

    def __init__(self, name: str, is_dir: bool) -> None:
        self.name = name
        self.is_dir = is_dir
        self.children: list[_TreeNode] = []


_BRACE_GLOB_RE = re.compile(r"\{([^{}]+)\}")


def expand_brace_globs(pattern: str) -> list[str]:
    """Expand one level of ``{a,b}`` alternatives (pathlib globs do not).

    ``*.{ts,tsx}`` → ``['*.ts', '*.tsx']``. Nested / empty braces are left as-is
    (single-element list). Order is stable; duplicates are dropped.
    """
    raw = (pattern or "*").strip() or "*"
    match = _BRACE_GLOB_RE.search(raw)
    if match is None:
        return [raw]
    alternatives = [part.strip() for part in match.group(1).split(",") if part.strip()]
    if not alternatives:
        return [raw]
    prefix = raw[: match.start()]
    suffix = raw[match.end() :]
    expanded: list[str] = []
    seen: set[str] = set()
    for alt in alternatives:
        item = f"{prefix}{alt}{suffix}"
        if item not in seen:
            seen.add(item)
            expanded.append(item)
    return expanded or [raw]


def _pattern_filters(pattern: str) -> bool:
    """True when ``pattern`` is narrower than「列全部」."""
    p = (pattern or "*").strip() or "*"
    return p != "*"


def _no_match_hint(
    *,
    pattern: str,
    directory: str,
    bare_entries: list,
    recursive: bool,
) -> str:
    """Actionable message when a glob matched nothing in a non-empty directory."""
    sample_parts: list[str] = []
    for entry in bare_entries[:8]:
        sample_parts.append(f"{'d ' if entry.is_dir else 'f '}{entry.path}")
    sample = "；".join(sample_parts)
    more = (
        f" 等共 {len(bare_entries)} 项"
        if len(bare_entries) > 8
        else f"（共 {len(bare_entries)} 项）"
    )
    tips = ["去掉 pattern", "换更宽的 glob"]
    if not recursive:
        tips.insert(0, "设 recursive=true 以搜索子目录")
    tip_text = "、".join(tips)
    root = "./" if directory in (".", "") else f"{directory.rstrip('/')}/"
    return (
        f"（在 {root} 下无匹配 pattern={pattern!r} 的条目；目录非空{more}。"
        f"可见顶层示例：{sample}。可{tip_text}。）"
    )


def _render_file_tree(
    entries: list[TreeEntry],
    directory: str,
    max_depth: int,
    truncated: bool,
    elided_count: int,
    *,
    empty_message: str | None = None,
) -> str:
    """Render ``list_tree`` entries as an ASCII tree (``├──`` / ``└──`` / ``│``)."""
    root_label = "./" if directory == "." else f"{directory.rstrip('/')}/"
    lines: list[str] = [root_label]

    if not entries:
        empty = empty_message or "（空目录）"
        return f"{root_label}\n{empty}\n\n（{max_depth} 层深度，共 0 条目）"

    dir_base = "" if directory == "." else directory.rstrip("/")
    root_name = "." if directory == "." else directory.rstrip("/").split("/")[-1]
    root = _TreeNode(root_name, True)

    for entry in sorted(entries, key=lambda e: e.path.lower()):
        parts = entry.path.split("/")
        if dir_base:
            base_parts = dir_base.split("/")
            if parts[: len(base_parts)] != base_parts:
                continue
            parts = parts[len(base_parts) :]
        if not parts:
            continue

        current = root
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            child = next((c for c in current.children if c.name == part), None)
            if child is None:
                child = _TreeNode(part, entry.is_dir if is_last else True)
                current.children.append(child)
            elif is_last:
                child.is_dir = entry.is_dir
            current = child

    def emit(children: list[_TreeNode], prefix: str) -> None:
        ordered = sorted(children, key=lambda n: (not n.is_dir, n.name.lower()))
        for i, child in enumerate(ordered):
            is_last = i == len(ordered) - 1
            branch = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "
            name = f"{child.name}/" if child.is_dir else child.name
            lines.append(prefix + branch + name)
            if child.children:
                emit(child.children, prefix + extension)

    emit(root.children, "")

    footer = f"\n\n（{max_depth} 层深度，共 {len(entries)} 条目"
    if truncated and elided_count:
        footer += f"；另有 {elided_count} 个条目因深度/预算未展开"
    footer += "）"
    return "\n".join(lines) + footer


def _error(error: str, start: float, *, contract_failure: bool = False) -> ToolResult:
    """Build a failed ToolResult with elapsed timing.

    ``contract_failure`` marks a self-correctable argument-contract rejection (e.g. a
    concurrent-write collision the model fixes by renaming) so the run-scoped tool
    circuit breaker skips it — see :class:`~agentcore.tools.protocol.ToolResult`.
    """
    return ToolResult(
        tool_call_id="",
        success=False,
        output="",
        error=error,
        duration_ms=int((time.monotonic() - start) * 1000),
        contract_failure=contract_failure,
    )


def _outside_workspace_msg(path: str, *, location: str | None = None) -> str:
    """Actionable OutsideWorkspace text.

    A bare "out of range" leaves the model guessing; the real cause is almost always
    an absolute sandbox path (``/workspace/report.md``) the guard refuses. Spell out
    the fix — a path relative to the workspace root — with a concrete example, so the
    worker corrects it in one shot instead of burning retry rounds.

    On cloud (``location=server``), also point at the bind card when the model was
    reaching for the user's machine — desktop-online qualifier matches other hard gates.
    """
    relative_fix = (
        "请改用相对工作区根目录的【相对路径】"
        "（不要用 /workspace/... 这类绝对路径），例如 research/report.md。"
    )
    if location == "server":
        return (
            f"路径 '{path}' 超出了工作区范围。"
            "若需访问用户本机目录：桌面在线时立即发 ask_user 卡"
            "（action=bind_local_folder），勿用纯文本询问；"
            f"若本意是工作区内文件：{relative_fix}"
        )
    return f"路径 '{path}' 超出了工作区范围。{relative_fix}"


def _log_write_collision(
    event: str,
    *,
    path: str,
    run_id: str,
    owner: str,
) -> None:
    """Log a write-ownership collision with a literal event name (catalog scan)."""
    # Literals required so sync_log_event_registry picks them up.
    if event == "file_write.collision":
        logger.info("file_write.collision", path=path, run_id=run_id, owner=owner)
    elif event == "file_append.collision":
        logger.info("file_append.collision", path=path, run_id=run_id, owner=owner)
    elif event == "str_replace.collision":
        logger.info("str_replace.collision", path=path, run_id=run_id, owner=owner)
    elif event == "write_section.collision":
        logger.info("write_section.collision", path=path, run_id=run_id, owner=owner)
    elif event == "file_delete.collision":
        logger.info("file_delete.collision", path=path, run_id=run_id, owner=owner)
    elif event == "file_move.collision":
        logger.info("file_move.collision", path=path, run_id=run_id, owner=owner)
    else:
        logger.info(event, path=path, run_id=run_id, owner=owner)


def _claim_write_path(
    context: ToolContext,
    rel_path: str,
    *,
    event: str,
    start: float,
) -> tuple[ToolResult | None, bool]:
    """C3 / batch ownership gate.

    Returns ``(error_result, release_on_fail)``. On conflict, ``error_result`` is set and
    ``release_on_fail`` is False. On success / no coordinator, ``error_result`` is None;
    ``release_on_fail`` is True only when this call newly acquired an *unowned* path
    (so a later I/O failure can free it without wiping a dispatch-time declare).
    """
    coordinator = context.write_coordinator
    if coordinator is None:
        return None, False
    prior = coordinator.owner_of(rel_path)
    owner = coordinator.claim(rel_path, context.run_id, context.write_ancestors)
    if owner is not None:
        _log_write_collision(
            event, path=rel_path, run_id=context.run_id, owner=owner
        )
        from agentcore.runtime.audit.hooks import on_write_conflict
        from agentcore.workspace.write_claims import ownership_conflict_message

        on_write_conflict(
            path=rel_path,
            run_id=context.run_id,
            owner_run_id=owner,
        )
        return (
            _error(
                ownership_conflict_message(rel_path, owner),
                start,
                contract_failure=True,
            ),
            False,
        )
    # Newly claimed empty path → release on failed I/O; already ours (declare) → keep.
    return None, prior is None



def _maybe_inject_research_ledger_anchors(
    rel_path: str, content: str, context: ToolContext
) -> str:
    """``research/`` 落盘时若正文无 ``#rN``，用本 worker 台账条目补脚注（一层兜底）。"""
    norm = (rel_path or "").replace("\\", "/").lstrip("./")
    if not norm.startswith("research/") or not norm.endswith(".md"):
        return content
    try:
        from agentcore.runtime.debate.research_dossier import (
            ensure_research_file_anchors,
        )
        from agentcore.runtime.suspension import turn_evidence_ledger
    except Exception:  # noqa: BLE001 — 导入失败不挡写入
        return content
    ledger = turn_evidence_ledger.get()
    if ledger is None:
        return content
    try:
        entries = list(ledger.all_entries())
    except Exception:  # noqa: BLE001
        return content
    registrant = f"worker:{context.agent_id}" if context.agent_id else ""
    mine = [
        e
        for e in entries
        if isinstance(e, dict)
        and (not registrant or str(e.get("registrant") or "") == registrant)
    ]
    # 本 worker 无登记时不跨员拼脚注（避免四路透镜互染）。
    if not mine:
        return content
    try:
        return ensure_research_file_anchors(content, mine)
    except Exception:  # noqa: BLE001
        logger.warning(
            "research.ledger_anchor_inject_failed",
            path=norm,
            error="ensure_failed",
        )
        return content


def _note_file_read_success(
    context: ToolContext,
    path_key: str,
    output: str,
    *,
    using_reread: bool,
) -> str:
    """Bump ``file_read_counts`` (and consume sticky re-read grant); append tip."""
    from agentcore.runtime.runs.constants import FILE_READ_SAME_PATH_MAX

    context.file_read_counts[path_key] = int(context.file_read_counts.get(path_key, 0)) + 1
    if using_reread:
        remaining = int(context.file_read_reread_remaining.get(path_key, 0))
        context.file_read_reread_remaining[path_key] = max(0, remaining - 1)
        if context.file_read_reread_remaining[path_key] <= 0:
            output += (
                f"\n\n[系统提示] `{path_key}` 的清理后再读次数已用尽；"
                "请依据本次正文或清理摘要推进，勿再重复 file_read。"
            )
        return output
    if context.file_read_counts[path_key] >= FILE_READ_SAME_PATH_MAX:
        output += (
            f"\n\n[系统提示] 本 run 对 `{path_key}` 的 file_read 已达上限 "
            f"（{FILE_READ_SAME_PATH_MAX} 次）；请停止重复读取，改用已有正文落盘。"
        )
    return output


class FileReadTool:
    """Read the contents of a file within the workspace."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_BOTH,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_read",
            description=(
                "读取工作区内某个文件的内容（相对路径）。"
                "宜在 grep / code_search 命中后再读；优先传 offset/limit 精读片段，"
                "禁止无目标地整目录逐文件通读。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "工作区内的相对文件路径",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "起始行号（1-based，含）。省略则从第 1 行开始。",
                        "minimum": 1,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多读取行数。省略则读到文件末尾（上限 500 行）。",
                        "minimum": 1,
                        "maximum": 500,
                    },
                },
                "required": ["path"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        rel_path = arguments.get("path", "")
        offset = arguments.get("offset")
        limit = arguments.get("limit")
        use_range = offset is not None or limit is not None

        # Wave3 B + R1: same-path ceiling; after tool_clear removes verbatim bodies
        # from the projected window, a sticky +1 re-read grant may apply.
        from agentcore.runtime.runs.constants import FILE_READ_SAME_PATH_MAX

        path_key = (rel_path or "").strip().replace("\\", "/")
        using_reread = False
        if path_key:
            prior = int(context.file_read_counts.get(path_key, 0))
            if prior >= FILE_READ_SAME_PATH_MAX:
                verbatim = context.file_read_verbatim_paths
                # None = projection not synced (unit tests / non-engine paths) →
                # treat as body still present (legacy hard cap).
                body_present = verbatim is None or path_key in verbatim
                remaining = int(context.file_read_reread_remaining.get(path_key, 0))
                if body_present:
                    return _error(
                        (
                            f"已多次读取 `{path_key}`（本 run 上限 "
                            f"{FILE_READ_SAME_PATH_MAX} 次）。请使用对话中已有正文，"
                            "勿重复 file_read 空转；缺细节改用 offset/limit 精读其它文件，"
                            "或基于已注入的契约摘要直接落盘。"
                        ),
                        start,
                        contract_failure=True,
                    )
                if remaining <= 0:
                    return _error(
                        (
                            f"已多次读取 `{path_key}`，且上下文中的正文已被清理、"
                            "再读次数已用尽。请依据清理摘要推进，或读取其它文件 / 落盘；"
                            "勿空转重复 file_read。"
                        ),
                        start,
                        contract_failure=True,
                    )
                using_reread = True

        try:
            if use_range:
                eff_offset = int(offset) if offset is not None else 1
                eff_limit = int(limit) if limit is not None else _DEFAULT_READ_LINES
                result = await context.backend.read_lines(
                    rel_path, offset=eff_offset, limit=eff_limit
                )
            else:
                content = await context.backend.read(rel_path)
                content = _truncate_content_lines(content, _DEFAULT_READ_LINES)
                if path_key:
                    content = _note_file_read_success(
                        context, path_key, content, using_reread=using_reread
                    )
                return ToolResult(
                    tool_call_id="",
                    success=True,
                    output=content,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
        except OutsideWorkspace:
            return _error(
                _outside_workspace_msg(rel_path, location=context.backend.location),
                start,
            )
        except PathNotFound:
            return _error(f"文件不存在：{rel_path}", start)
        except NotAFile:
            return _error(f"不是文件：{rel_path}", start)
        except WorkspaceError as e:
            return _error(f"读取文件失败：{e}", start)

        body = _format_numbered_lines(result.lines, result.start_line)
        footer = (
            f"\n\n（第 {result.start_line}–{result.end_line} 行，共 {result.total_lines} 行）"
        )
        output = body + footer if body else footer.lstrip()

        if path_key:
            output = _note_file_read_success(
                context, path_key, output, using_reread=using_reread
            )

        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
        )


class FileWriteTool:
    """Write content to a file within the workspace."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_write",
            description=(
                "把内容写入文件：会创建该文件（含所有上级目录），或【整体覆盖】"
                "已有文件。用它来【新建】文件。"
                "【大产物默认】骨架 file_write + 分段 file_append："
                "先写结构/首段，后续各节用 file_append 追加——"
                "不要单次一口气塞完整站 HTML / 长文。"
                "【修订已有成品】禁止用它全文重写——对已存在成篇非空文件，"
                "系统会【硬拒绝】整文件覆盖并引导改用 str_replace / file_append"
                "（反例：惰性「……（中间省略，已保留首尾）……」会残缺交付）。"
                "只改一部分优先 str_replace；末尾追加用 file_append。"
                "路径必须是相对于工作区的相对路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "工作区内的相对文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "要写入的内容。大文件请只放骨架或首段，"
                            "其余用 file_append 分段追加。"
                        ),
                    },
                },
                "required": ["path", "content"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.GRANTABLE,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        rel_path = arguments.get("path", "")
        content = arguments.get("content", "")

        # A missing/empty path resolves to the workspace root (a directory); writing
        # onto it raises a cryptic OS error (Permission denied / IsADirectory) that
        # leaks the absolute server path and gives the model nothing to act on. Fail
        # fast with the required-arg message instead (parity with str_replace/move).
        if not rel_path:
            return _error("path 不能为空：请提供工作区内的相对文件路径（如 report.md）", start)

        # 并行写隔离·硬约束 (C3): refuse overwrite when another run owns the path.
        # Claimed BEFORE the awaited write; ancestor handoff still allowed.
        denied, release_on_fail = _claim_write_path(
            context, rel_path, event="file_write.collision", start=start
        )
        if denied is not None:
            return denied
        coordinator = context.write_coordinator

        # 幕1 案卷落盘锚：research/ 下若正文无 #rN，用本回合台账条目写脚注（一层兜底）。
        write_content = _maybe_inject_research_ledger_anchors(
            rel_path, content, context
        )

        # Pre-read for overwrite integrity nudge + substantial-file hard reject.
        old_content: str | None = None
        try:
            old_content = await context.backend.read(rel_path)
        except PathNotFound:
            old_content = None
        except WorkspaceError:
            old_content = None

        if old_content is not None and is_substantial_existing_body(old_content):
            old_chars = len(old_content.strip())
            logger.info(
                "file_write.substantial_overwrite_rejected",
                path=rel_path,
                old_chars=old_chars,
            )
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                substantial_overwrite_rejection(rel_path, old_chars),
                start,
                contract_failure=True,
            )

        try:
            written = await context.backend.write(rel_path, write_content)
        except OutsideWorkspace:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                _outside_workspace_msg(rel_path, location=context.backend.location),
                start,
            )
        except WorkspaceError as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"写入文件失败：{e}", start)

        anchor_note = (
            "；已补写来源台账锚脚注"
            if write_content != content
            else ""
        )
        # file_write 是整体写入，内容就是你本次提交的全文 → 无需回显（模型已持有），只在回执里
        # 点明「已落盘、无需回读」即可（见本模块顶部说明）。
        output = (
            f"已写入 {written} 字节到 {rel_path}"
            "（内容即你本次提交的全文，已落盘，无需再读回确认）"
            f"{anchor_note}"
        )
        if old_content is not None:
            nudge = overwrite_integrity_nudge(rel_path, old_content, write_content)
            if nudge:
                logger.info(
                    "file_write.integrity_nudge",
                    path=rel_path,
                    old_chars=len(old_content),
                    new_chars=len(write_content),
                )
                output += nudge
        # Soft length nudge (independent of overwrite integrity): suggest skeleton +
        # append for oversized bodies. Never blocks; fires on new files too.
        length_nudge = write_length_nudge(rel_path, write_content)
        if length_nudge:
            logger.info(
                "file_write.length_nudge",
                path=rel_path,
                chars=len(write_content),
                warn_chars=_WRITE_LENGTH_WARN_CHARS,
            )
            output += length_nudge
        _mark_landed_files(context)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
        )


class FileAppendTool:
    """Append content to the end of a file within the workspace."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_append",
            description=(
                "在文件【末尾追加】内容：文件不存在则创建（含上级目录）；已存在则在"
                "末尾拼接，不重写全文。"
                "大产物默认写法的后半段：骨架已用 file_write 落盘后，用本工具逐节追加"
                "（整站 HTML / 长文 / 多章节文档）。"
                "若要【整体覆盖】或新建首段/骨架，用 file_write；若要改中间某段，用 "
                "str_replace。路径必须是相对于工作区的相对路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "工作区内的相对文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "要追加到文件末尾的内容（一节/一段为宜；"
                            "自行带好段落分隔，如 leading \\n\\n）。"
                        ),
                    },
                },
                "required": ["path", "content"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.GRANTABLE,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        rel_path = arguments.get("path", "")
        content = arguments.get("content", "")

        if not rel_path:
            return _error("path 不能为空：请提供工作区内的相对文件路径（如 report.md）", start)

        denied, release_on_fail = _claim_write_path(
            context, rel_path, event="file_append.collision", start=start
        )
        if denied is not None:
            return denied
        coordinator = context.write_coordinator

        try:
            appended = await context.backend.append(rel_path, content)
        except OutsideWorkspace:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                _outside_workspace_msg(rel_path, location=context.backend.location),
                start,
            )
        except NotAFile:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"不是文件：{rel_path}", start)
        except WorkspaceError as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"追加文件失败：{e}", start)

        _mark_landed_files(context)
        return ToolResult(
            tool_call_id="",
            success=True,
            # 回显合并后的文件末尾：append 只写增量、模型上下文里没有合并后的全文，故把「文件当前
            # 末尾」当场给它，免得它为「看看追加落对没」再花一轮 read 回读（见本模块顶部说明）。
            output=(
                f"已追加 {appended} 字节到 {rel_path}（已落盘，无需再读回确认）。文件当前末尾：\n"
                + _tail_preview(
                    await context.backend.read(rel_path),
                    max_lines=_APPEND_ECHO_LINES,
                    max_chars=_APPEND_ECHO_CHARS,
                )
            ),
            duration_ms=int((time.monotonic() - start) * 1000),
        )


class FileListTool:
    """List files in a directory within the workspace."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_BOTH,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_list",
            description=(
                "列出某个目录下的文件与子目录。路径必须是相对于工作区的相对路径。"
                "默认只列当前层（recursive=false）：`*.py` 不会进入子目录；"
                "要搜整棵树请设 recursive=true。支持 `{ts,tsx}` 花括号二选一。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "相对目录路径（默认：工作区根目录）",
                        "default": ".",
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "用于过滤结果的 glob 模式（如 '*.py'、'*.{ts,tsx}'）。"
                            "非递归时只匹配当前层文件名。"
                        ),
                        "default": "*",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "递归列出子目录（树形）。默认 false（仅当前层）。",
                        "default": False,
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "递归最大深度（仅 recursive=true 时生效）。默认 3，上限 8。",
                        "default": 3,
                        "minimum": 1,
                        "maximum": 8,
                    },
                },
                "required": [],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        directory = arguments.get("directory", ".")
        pattern = arguments.get("pattern", "*") or "*"
        recursive = bool(arguments.get("recursive", False))
        max_depth = int(arguments.get("max_depth", 3))
        max_depth = max(1, min(max_depth, 8))
        patterns = expand_brace_globs(str(pattern))

        try:
            if recursive:
                merged: dict[str, TreeEntry] = {}
                truncated = False
                elided_count = 0
                for pat in patterns:
                    tree = await context.backend.list_tree(
                        directory, pattern=pat, max_depth=max_depth
                    )
                    for entry in tree.entries:
                        merged[entry.path] = entry
                    truncated = truncated or tree.truncated
                    elided_count += tree.elided_count
                entries_tree = list(merged.values())
                empty_message = None
                if not entries_tree and _pattern_filters(str(pattern)):
                    bare = [
                        e
                        for e in await context.backend.list(directory, "*")
                        if e.is_dir or not is_ai_noise_file_name(basename(e.path))
                    ]
                    if bare:
                        empty_message = _no_match_hint(
                            pattern=str(pattern),
                            directory=str(directory),
                            bare_entries=bare,
                            recursive=True,
                        )
                output = _render_file_tree(
                    entries_tree,
                    directory,
                    max_depth,
                    truncated,
                    elided_count,
                    empty_message=empty_message,
                )
            else:
                # ``list`` is shared with user UI (system-noise only); strip AI
                # noise here so media/archives don't pollute the agent view.
                seen: set[str] = set()
                entries: list[DirEntry] = []
                for pat in patterns:
                    for dir_entry in await context.backend.list(directory, pat):
                        if dir_entry.path in seen:
                            continue
                        if dir_entry.is_dir or not is_ai_noise_file_name(
                            basename(dir_entry.path)
                        ):
                            seen.add(dir_entry.path)
                            entries.append(dir_entry)
                if entries:
                    output = "\n".join(
                        f"{'d ' if e.is_dir else 'f '}{e.path}" for e in entries
                    )
                elif _pattern_filters(str(pattern)):
                    bare = [
                        e
                        for e in await context.backend.list(directory, "*")
                        if e.is_dir or not is_ai_noise_file_name(basename(e.path))
                    ]
                    if bare:
                        output = _no_match_hint(
                            pattern=str(pattern),
                            directory=str(directory),
                            bare_entries=bare,
                            recursive=False,
                        )
                    else:
                        output = "（空目录）"
                else:
                    output = "（空目录）"
        except OutsideWorkspace:
            return _error(
                _outside_workspace_msg(directory, location=context.backend.location),
                start,
            )
        except NotADirectory:
            return _error(f"不是目录：{directory}", start)
        except WorkspaceError as e:
            return _error(f"列目录失败：{e}", start)

        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
        )


class StrReplaceTool:
    """Replace an exact text span in an existing workspace file (precise edit)."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="str_replace",
            description=(
                "通过替换【完全精确匹配的文本片段】来编辑已有文件。改文件时优先"
                "用它而非 file_write：它只重写匹配到的片段，因此对大文件安全、也"
                "不会误伤无关内容。在 old_string 里放足够的上下文，确保在文件中"
                "【唯一匹配一次】（包括空白、缩进与换行）。若 old_string 不存在、"
                "或匹配多于一次（除非 replace_all=true），则失败。要新建文件请改"
                "用 file_write。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "工作区内的相对文件路径",
                    },
                    "old_string": {
                        "type": "string",
                        "description": ("要替换的精确文本，需带足够的上下文以在文件中唯一。"),
                    },
                    "new_string": {
                        "type": "string",
                        "description": "替换后的文本（必须与 old_string 不同）。",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": ("替换所有出现处，而非要求唯一匹配（默认 false）。"),
                        "default": False,
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.GRANTABLE,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        rel_path = arguments.get("path", "")
        old_string = arguments.get("old_string", "")
        new_string = arguments.get("new_string", "")
        replace_all = bool(arguments.get("replace_all", False))

        if not old_string:
            return _error("old_string 不能为空", start)
        if old_string == new_string:
            return _error("old_string 与 new_string 相同，没有需要改动的内容", start)

        denied, release_on_fail = _claim_write_path(
            context, rel_path, event="str_replace.collision", start=start
        )
        if denied is not None:
            return denied
        coordinator = context.write_coordinator

        try:
            outcome = await context.backend.replace(
                rel_path, old_string, new_string, all_=replace_all
            )
        except OutsideWorkspace:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                _outside_workspace_msg(rel_path, location=context.backend.location),
                start,
            )
        except PathNotFound:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"文件不存在：{rel_path}", start)
        except NotAFile:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"不是文件：{rel_path}", start)
        except NotUTF8:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"无法编辑二进制 / 非 UTF-8 文件：{rel_path}", start)
        except NoMatch:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                f"在 {rel_path} 中找不到 old_string；它必须与文件完全一致，包括空白与缩进。",
                start,
            )
        except AmbiguousMatch as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                f"old_string 在 {rel_path} 中不唯一（匹配 {e.count} 处）。请补充"
                "更多上下文以锁定单一片段，或设置 replace_all=true。",
                start,
            )
        except WorkspaceError as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"写入文件失败：{e}", start)

        loc = "" if outcome.first_line is None else f"（约第 {outcome.first_line} 行）"
        # 回显改动落点的上下文（所改即所见），免得 worker 为「确认替换落对没」再花一轮 read 回读
        # （见本模块顶部说明）。有界：落点前后各 _EDIT_ECHO_CONTEXT 行 + 新增行数，封顶 MAX_LINES。
        echo = ""
        if outcome.first_line is not None:
            region = await context.backend.read_lines(
                rel_path,
                offset=max(1, outcome.first_line - _EDIT_ECHO_CONTEXT),
                limit=min(
                    _EDIT_ECHO_CONTEXT * 2 + 1 + new_string.count("\n"),
                    _EDIT_ECHO_MAX_LINES,
                ),
            )
            echo = "。改动落点（已落盘，无需再读回确认）：\n" + _format_numbered_lines(
                region.lines, region.start_line
            )
        _mark_landed_files(context)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已在 {rel_path} 替换 {outcome.count} 处{loc}{echo}",
            duration_ms=int((time.monotonic() - start) * 1000),
            metadata={"replacements": outcome.count},
        )


class WriteSectionTool:
    """Inject HTML into a ``<!-- SECTION:sN START/END -->`` pair (build_website assemble).

    Hard write contract: does not require an exact match of the prior placeholder
    body — only the SECTION markers — so indent / whitespace drift cannot fail
    the fill the way fragile ``str_replace`` can.
    """

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="write_section",
            description=(
                "把 HTML 正文写入已有文件中的一对 SECTION 注释标记之间"
                "（`<!-- SECTION:sN START -->`…`<!-- SECTION:sN END -->`）。"
                "用于建站 assemble / 分区填槽：【不必】精确匹配旧占位正文，"
                "也不怕缩进漂移——只认标记对。content 与 from_file 二选一；"
                "保留标记注释本身。新建整文件请用 file_write；精确改任意片段请用 "
                "str_replace。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "含 SECTION 标记的工作区相对路径（通常 site/index.html）",
                    },
                    "section": {
                        "type": "string",
                        "description": "分区标记名，如 s0 / s1（与骨架 CONTRACT 一致）",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入标记对之间的 HTML 片段正文（勿再包 html/head/body）",
                    },
                    "from_file": {
                        "type": "string",
                        "description": (
                            "可选：从该相对路径读取片段正文再注入"
                            "（与 content 二选一；常用于 site/sections/sN.html）"
                        ),
                    },
                },
                "required": ["path", "section"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.GRANTABLE,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        from agentcore.runtime.runs.website_section import (
            SectionMarkerError,
            inject_section_html,
            normalize_section_id,
        )

        start = time.monotonic()
        rel_path = (arguments.get("path") or "").strip()
        section_raw = arguments.get("section", "")
        content_arg = arguments.get("content")
        from_file = (arguments.get("from_file") or "").strip()

        if not rel_path:
            return _error("path 不能为空：请提供含 SECTION 标记的相对路径", start)
        if content_arg is not None and from_file:
            return _error("content 与 from_file 只能提供其一", start)
        if content_arg is None and not from_file:
            return _error("须提供 content 或 from_file（分区 HTML 正文来源）", start)

        denied, release_on_fail = _claim_write_path(
            context, rel_path, event="write_section.collision", start=start
        )
        if denied is not None:
            return denied
        coordinator = context.write_coordinator

        try:
            slug = normalize_section_id(str(section_raw))
        except SectionMarkerError as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(str(e), start)

        body: str
        if from_file:
            try:
                body = await context.backend.read(from_file)
            except OutsideWorkspace:
                if coordinator is not None and release_on_fail:
                    coordinator.release(rel_path, context.run_id)
                return _error(
                    _outside_workspace_msg(from_file, location=context.backend.location),
                    start,
                )
            except PathNotFound:
                if coordinator is not None and release_on_fail:
                    coordinator.release(rel_path, context.run_id)
                return _error(f"片段文件不存在：{from_file}", start)
            except NotAFile:
                if coordinator is not None and release_on_fail:
                    coordinator.release(rel_path, context.run_id)
                return _error(f"不是文件：{from_file}", start)
            except NotUTF8:
                if coordinator is not None and release_on_fail:
                    coordinator.release(rel_path, context.run_id)
                return _error(f"无法读取二进制 / 非 UTF-8 文件：{from_file}", start)
            except WorkspaceError as e:
                if coordinator is not None and release_on_fail:
                    coordinator.release(rel_path, context.run_id)
                return _error(f"读取片段失败：{e}", start)
        else:
            body = str(content_arg if content_arg is not None else "")

        try:
            old = await context.backend.read(rel_path)
        except OutsideWorkspace:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                _outside_workspace_msg(rel_path, location=context.backend.location),
                start,
            )
        except PathNotFound:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"文件不存在：{rel_path}", start)
        except NotAFile:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"不是文件：{rel_path}", start)
        except NotUTF8:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"无法编辑二进制 / 非 UTF-8 文件：{rel_path}", start)
        except WorkspaceError as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"读取文件失败：{e}", start)

        try:
            new_html = inject_section_html(old, slug, body)
        except SectionMarkerError as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(str(e), start, contract_failure=True)

        if new_html == old:
            return ToolResult(
                tool_call_id="",
                success=True,
                output=f"SECTION:{slug} 在 {rel_path} 已是目标正文，无需改动",
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={"section": slug, "unchanged": True},
            )

        try:
            await context.backend.write(rel_path, new_html)
        except OutsideWorkspace:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                _outside_workspace_msg(rel_path, location=context.backend.location),
                start,
            )
        except WorkspaceError as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"写入文件失败：{e}", start)

        _mark_landed_files(context)
        src = f"（来自 `{from_file}`）" if from_file else ""
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已将 SECTION:{slug} 写入 {rel_path}{src}",
            duration_ms=int((time.monotonic() - start) * 1000),
            metadata={"section": slug, "path": rel_path},
        )


class FileDeleteTool:
    """Delete a file, or a directory and all its contents, within the workspace."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_delete",
            description=(
                "删除一个文件，或一个目录【及其全部内容】（递归）。默认【可逆】："
                "本地模式移入系统回收站；云端 / 无回收站环境移入工作区软删除区"
                "（.agentcore/trash，保留还原所需信息）。仅当 permanent=true 时"
                "才永久删除。工作区根目录本身不可删除。路径必须是相对于工作区的"
                "相对路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的文件或目录的相对路径",
                    },
                    "permanent": {
                        "type": "boolean",
                        "description": (
                            "true = 永久删除（不可恢复）；默认 false = 可逆删除"
                            "（回收站 / 工作区软删区）。"
                        ),
                        "default": False,
                    },
                },
                "required": ["path"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.GRANTABLE,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        rel_path = arguments.get("path", "")
        permanent = bool(arguments.get("permanent", False))

        if not rel_path:
            return _error("path 不能为空：请提供工作区内的相对文件路径", start)

        denied, release_on_fail = _claim_write_path(
            context, rel_path, event="file_delete.collision", start=start
        )
        if denied is not None:
            return denied
        coordinator = context.write_coordinator

        # 成篇质量：禁止「删长文 → 整篇重写」烧预算；与 file_write 成篇覆盖硬拒同阈值。
        old_content: str | None = None
        try:
            old_content = await context.backend.read(rel_path)
        except PathNotFound:
            old_content = None
        except WorkspaceError:
            # Directory / binary / outside — let delete path surface the real error.
            old_content = None
        if old_content is not None and is_substantial_existing_body(old_content):
            old_chars = len(old_content.strip())
            logger.info(
                "file_delete.substantial_rejected",
                path=rel_path,
                old_chars=old_chars,
            )
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                substantial_delete_rejection(rel_path, old_chars),
                start,
                contract_failure=True,
            )

        try:
            await context.backend.delete(rel_path, permanent=permanent)
        except OutsideWorkspace:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(
                _outside_workspace_msg(rel_path, location=context.backend.location),
                start,
            )
        except PathNotFound:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"路径不存在：{rel_path}", start)
        except WorkspaceError as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            return _error(f"删除失败：{e}", start)

        if permanent:
            msg = f"已永久删除 {rel_path}"
        else:
            msg = (
                f"已可逆删除 {rel_path}"
                "（本地通道→系统回收站；云端/sidecar→工作区 .agentcore/trash）"
            )

        return ToolResult(
            tool_call_id="",
            success=True,
            output=msg,
            duration_ms=int((time.monotonic() - start) * 1000),
        )


class FileMoveTool:
    """Move or rename a file or directory within the workspace."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_move",
            description=(
                "在工作区内移动或重命名文件 / 目录。可用于重命名（在同一目录内"
                "移动）或把路径迁到新位置；目标路径缺失的上级目录会自动创建。若"
                "目标已存在则失败——【不会覆盖】。两个路径都必须是相对于工作区的"
                "相对路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "要移动的已有文件 / 目录的相对路径",
                    },
                    "destination": {
                        "type": "string",
                        "description": "目标相对路径（必须尚不存在）",
                    },
                },
                "required": ["source", "destination"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.GRANTABLE,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        source = arguments.get("source", "")
        destination = arguments.get("destination", "")

        if not source or not destination:
            return _error("'source' 与 'destination' 均为必填", start)
        if source == destination:
            return _error("source 与 destination 相同，无需移动", start)

        # Ownership: source must be ours (or free); destination must not be held by another.
        denied_src, release_src = _claim_write_path(
            context, source, event="file_move.collision", start=start
        )
        if denied_src is not None:
            return denied_src
        denied_dst, release_dst = _claim_write_path(
            context, destination, event="file_move.collision", start=start
        )
        if denied_dst is not None:
            coordinator = context.write_coordinator
            if coordinator is not None and release_src:
                coordinator.release(source, context.run_id)
            return denied_dst
        coordinator = context.write_coordinator

        try:
            await context.backend.move(source, destination)
        except OutsideWorkspace as e:
            if coordinator is not None:
                if release_src:
                    coordinator.release(source, context.run_id)
                if release_dst:
                    coordinator.release(destination, context.run_id)
            return _error(_outside_workspace_msg(str(e), location=context.backend.location), start)
        except PathNotFound:
            if coordinator is not None:
                if release_src:
                    coordinator.release(source, context.run_id)
                if release_dst:
                    coordinator.release(destination, context.run_id)
            return _error(f"源路径不存在：{source}", start)
        except AlreadyExists:
            if coordinator is not None:
                if release_src:
                    coordinator.release(source, context.run_id)
                if release_dst:
                    coordinator.release(destination, context.run_id)
            return _error(
                f"目标已存在：{destination}。请换一个不存在的路径，或先删除它。",
                start,
            )
        except WorkspaceError as e:
            if coordinator is not None:
                if release_src:
                    coordinator.release(source, context.run_id)
                if release_dst:
                    coordinator.release(destination, context.run_id)
            return _error(f"移动失败：{e}", start)

        # Successful move: drop source ownership key; destination already claimed.
        if coordinator is not None:
            coordinator.release(source, context.run_id)

        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已把 {source} 移动到 {destination}",
            duration_ms=int((time.monotonic() - start) * 1000),
        )


class FileCopyTool:
    """Copy a file or directory tree within the workspace (binary-safe)."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_copy",
            description=(
                "在工作区内复制文件或【目录树】（含二进制）。目标路径缺失的上级"
                "目录会自动创建；若目标已存在则失败——【不会覆盖】。不能复制到"
                "自身或其子目录。两个路径都必须是相对于工作区的相对路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "要复制的已有文件 / 目录的相对路径",
                    },
                    "destination": {
                        "type": "string",
                        "description": "目标相对路径（必须尚不存在）",
                    },
                },
                "required": ["source", "destination"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.GRANTABLE,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        source = arguments.get("source", "")
        destination = arguments.get("destination", "")

        if not source or not destination:
            return _error("'source' 与 'destination' 均为必填", start)
        if source == destination:
            return _error("source 与 destination 相同，无需复制", start)

        try:
            await context.backend.copy(source, destination)
        except OutsideWorkspace as e:
            return _error(_outside_workspace_msg(str(e), location=context.backend.location), start)
        except PathNotFound:
            return _error(f"源路径不存在：{source}", start)
        except AlreadyExists:
            return _error(
                f"目标已存在：{destination}。请换一个不存在的路径，或先删除它。",
                start,
            )
        except WorkspaceError as e:
            return _error(f"复制失败：{e}", start)

        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已把 {source} 复制到 {destination}",
            duration_ms=int((time.monotonic() - start) * 1000),
        )


class MkdirTool:
    """Create an empty directory (with parents) within the workspace."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="mkdir",
            description=(
                "在工作区内创建空目录（上级目录不存在时一并创建）。若路径已存在"
                "则失败。路径必须是相对于工作区的相对路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要创建的相对目录路径",
                    },
                },
                "required": ["path"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.GRANTABLE,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        rel_path = arguments.get("path", "")

        if not rel_path:
            return _error("path 不能为空：请提供工作区内的相对目录路径", start)

        try:
            await context.backend.mkdir(rel_path)
        except OutsideWorkspace:
            return _error(
                _outside_workspace_msg(rel_path, location=context.backend.location),
                start,
            )
        except AlreadyExists:
            return _error(f"路径已存在：{rel_path}", start)
        except WorkspaceError as e:
            return _error(f"创建目录失败：{e}", start)

        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已创建目录 {rel_path}",
            duration_ms=int((time.monotonic() - start) * 1000),
        )


_BATCH_OPS = frozenset({"move", "copy", "delete", "mkdir"})
_BATCH_MAX_OPS = 50


def _batch_op_label(item: dict[str, Any]) -> str:
    op = str(item.get("op", "")).strip()
    if op == "move":
        return f"move {item.get('source', '')} → {item.get('destination', '')}"
    if op == "copy":
        return f"copy {item.get('source', '')} → {item.get('destination', '')}"
    if op == "delete":
        perm = " (永久)" if item.get("permanent") else ""
        return f"delete {item.get('path', '')}{perm}"
    if op == "mkdir":
        return f"mkdir {item.get('path', '')}"
    return f"? {op}"


class FileBatchTool:
    """Apply multiple move/copy/delete/mkdir ops in one call (partial failure OK)."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_batch",
            description=(
                "一次提交多条工作区文件操作（move / copy / delete / mkdir）。"
                f"最多 {_BATCH_MAX_OPS} 项。逐项执行：单项失败不中断整批，回执如实"
                "列出成功 / 跳过 / 失败。目标同名冲突 = 跳过并入报告。"
                "整理方案确认后传入 organize_plan_id：仅允许方案内条目，且跳过二次审批。"
                "删除默认可逆；区外 permanent=true 一律拒绝。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "description": "按顺序执行的操作列表",
                        "minItems": 1,
                        "maxItems": _BATCH_MAX_OPS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {
                                    "type": "string",
                                    "enum": ["move", "copy", "delete", "mkdir"],
                                    "description": "操作类型",
                                },
                                "path": {
                                    "type": "string",
                                    "description": "delete / mkdir 的相对路径",
                                },
                                "source": {
                                    "type": "string",
                                    "description": "move / copy 的源相对路径",
                                },
                                "destination": {
                                    "type": "string",
                                    "description": "move / copy 的目标相对路径",
                                },
                                "permanent": {
                                    "type": "boolean",
                                    "description": "仅 delete：true = 永久删除（区外禁止）",
                                    "default": False,
                                },
                            },
                            "required": ["op"],
                        },
                    },
                    "organize_plan_id": {
                        "type": "string",
                        "description": (
                            "整理方案卡确认后返回的 plan_id。携带时：范围校验仅允许方案内"
                            "条目，并跳过 GRANTABLE 二次审批；执行成功项写入可撤销日志。"
                        ),
                    },
                    "organize_undo": {
                        "type": "boolean",
                        "description": (
                            "true = 撤销本会话最近一次整理（逆回放 move/mkdir；删除项只提示"
                            "去回收站）。单次有效。勿与 operations / organize_plan_id 同用。"
                        ),
                        "default": False,
                    },
                },
                "required": [],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.GRANTABLE,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        if bool(arguments.get("organize_undo")):
            return await self._undo(context, start)

        raw = arguments.get("operations")
        if not isinstance(raw, list) or not raw:
            return _error("operations 必须是非空数组（撤销请用 organize_undo=true）", start)
        if len(raw) > _BATCH_MAX_OPS:
            return _error(f"operations 最多 {_BATCH_MAX_OPS} 项", start)

        plan_id = str(arguments.get("organize_plan_id") or "").strip()
        if plan_id:
            from agentcore.workspace.organize_plan_store import get_plan, ops_within_plan

            plan = get_plan(plan_id)
            if plan is None or plan.conversation_id != context.conversation_id:
                return _error(f"整理方案不存在或已失效：{plan_id}", start)
            scope_err = ops_within_plan(plan, [i for i in raw if isinstance(i, dict)])
            if scope_err:
                return _error(scope_err, start)

        lines: list[str] = [f"本次共 {len(raw)} 项："]
        ok_n = skip_n = fail_n = 0
        successes: list[dict[str, Any]] = []

        for i, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                fail_n += 1
                lines.append(f"{i}. 失败 · 条目必须是对象")
                continue
            op = str(item.get("op", "")).strip()
            label = _batch_op_label(item)
            if op not in _BATCH_OPS:
                fail_n += 1
                lines.append(f"{i}. 失败 · {label}：未知 op")
                continue
            try:
                status, detail = await self._run_one(op, item, context)
            except Exception as e:  # noqa: BLE001 — batch must continue
                fail_n += 1
                lines.append(f"{i}. 失败 · {label}：{e}")
                continue
            if status == "ok":
                ok_n += 1
                lines.append(f"{i}. 成功 · {detail}")
                successes.append(item)
            elif status == "skip":
                skip_n += 1
                lines.append(f"{i}. 跳过 · {detail}")
            else:
                fail_n += 1
                lines.append(f"{i}. 失败 · {detail}")

        if plan_id and successes:
            from agentcore.workspace import organize_journal

            organize_journal.record_batch(
                conversation_id=context.conversation_id,
                plan_id=plan_id,
                successes=successes,
            )
            lines.append(
                f"已记录整理日志（plan={plan_id}）。可用 file_batch(organize_undo=true) 撤销"
                "本次 move/mkdir；删除项请到系统回收站手动恢复。"
            )

        summary = f"完成：成功 {ok_n}，跳过 {skip_n}，失败 {fail_n}"
        lines.append(summary)
        return ToolResult(
            tool_call_id="",
            success=fail_n == 0,
            output="\n".join(lines),
            error="" if fail_n == 0 else summary,
            duration_ms=int((time.monotonic() - start) * 1000),
            metadata={
                "ok": ok_n,
                "skip": skip_n,
                "fail": fail_n,
                "total": len(raw),
                "organize_plan_id": plan_id or None,
            },
        )

    async def _undo(self, context: ToolContext, start: float) -> ToolResult:
        from agentcore.workspace import organize_journal
        from agentcore.workspace.organize_plan_store import deactivate_plan

        journal = organize_journal.get_journal(context.conversation_id)
        if journal is None:
            return _error("没有可撤销的整理记录", start)
        if journal.undone:
            return _error("本次整理已撤销过（仅单次有效）", start)
        undo_ops, deletes = organize_journal.build_undo_operations(journal)
        lines: list[str] = ["撤销本次整理："]
        ok_n = skip_n = fail_n = 0
        for i, item in enumerate(undo_ops, start=1):
            op = str(item.get("op", "")).strip()
            try:
                status, detail = await self._run_one(op, item, context)
            except Exception as e:  # noqa: BLE001
                fail_n += 1
                lines.append(f"{i}. 失败 · {e}")
                continue
            if status == "ok":
                ok_n += 1
                lines.append(f"{i}. 成功 · {detail}")
            elif status == "skip":
                skip_n += 1
                lines.append(f"{i}. 跳过 · {detail}")
            else:
                fail_n += 1
                lines.append(f"{i}. 失败 · {detail}")
        if deletes:
            lines.append(
                "以下删除项未自动还原，请到系统回收站手动恢复：\n"
                + "\n".join(f"- {p}" for p in deletes)
            )
        organize_journal.mark_undone(context.conversation_id)
        deactivate_plan(journal.plan_id)
        summary = f"撤销完成：成功 {ok_n}，跳过 {skip_n}，失败 {fail_n}"
        lines.append(summary)
        return ToolResult(
            tool_call_id="",
            success=fail_n == 0,
            output="\n".join(lines),
            error="" if fail_n == 0 else summary,
            duration_ms=int((time.monotonic() - start) * 1000),
            metadata={"ok": ok_n, "skip": skip_n, "fail": fail_n, "undo": True},
        )

    async def _run_one(
        self, op: str, item: dict[str, Any], context: ToolContext
    ) -> tuple[str, str]:
        if op == "mkdir":
            path = str(item.get("path", "")).strip()
            if not path:
                return "fail", "mkdir · path 不能为空"
            try:
                await context.backend.mkdir(path)
            except AlreadyExists:
                return "skip", f"mkdir {path}（已存在）"
            except OutsideWorkspace:
                return "fail", _outside_workspace_msg(
                    path, location=context.backend.location
                )
            except WorkspaceError as e:
                return "fail", f"mkdir {path}：{e}"
            return "ok", f"mkdir {path}"

        if op == "delete":
            path = str(item.get("path", "")).strip()
            if not path:
                return "fail", "delete · path 不能为空"
            permanent = bool(item.get("permanent", False))
            try:
                await context.backend.delete(path, permanent=permanent)
            except PathNotFound:
                return "skip", f"delete {path}（不存在）"
            except OutsideWorkspace:
                return "fail", _outside_workspace_msg(
                    path, location=context.backend.location
                )
            except WorkspaceError as e:
                return "fail", f"delete {path}：{e}"
            mode = "永久删除" if permanent else "可逆删除"
            return "ok", f"delete {path}（{mode}）"

        source = str(item.get("source", "")).strip()
        destination = str(item.get("destination", "")).strip()
        if not source or not destination:
            return "fail", f"{op} · source 与 destination 均为必填"
        if source == destination:
            return "skip", f"{op} {source}（源与目标相同）"
        try:
            if op == "move":
                await context.backend.move(source, destination)
            else:
                await context.backend.copy(source, destination)
        except PathNotFound:
            return "fail", f"{op} {source} → {destination}：源不存在"
        except AlreadyExists:
            # MVP conflict policy: skip into report (提案钉死).
            return "skip", f"{op} {source} → {destination}：目标已存在"
        except OutsideWorkspace as e:
            return "fail", (
                f"{op} {source} → {destination}："
                + _outside_workspace_msg(str(e), location=context.backend.location)
            )
        except WorkspaceError as e:
            return "fail", f"{op} {source} → {destination}：{e}"
        return "ok", f"{op} {source} → {destination}"
