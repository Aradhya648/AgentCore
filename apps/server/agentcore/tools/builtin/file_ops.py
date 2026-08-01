"""File operations tools (read, write, list, precise str_replace edit, delete,
move, copy, mkdir, batch).

Thin shells over ``ToolContext.backend``: each tool parses arguments, calls the
workspace backend, maps typed ``WorkspaceError`` failures back to user-facing
messages, and renders a ``ToolResult``. All actual I/O and the path-traversal
guard live in the backend, so the same tools run unchanged against a server or a
local (desktop) workspace.
"""

import hashlib
import re
import time
from difflib import SequenceMatcher
from posixpath import basename
from typing import Any, Literal

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.tools.builtin.code_integrity import (
    code_omission_rejection,
    code_structure_rejection,
    is_brace_code_path,
)
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_BOTH,
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)
from agentcore.workspace._paths import is_ai_noise_file_name
from agentcore.workspace.attachment_parse import (
    MARKITDOWN_EXTENSIONS,
    SKIP_EXTENSIONS,
    ParseStatus,
    extension_of,
    extract_office_bytes,
    parsed_copy_path,
)
from agentcore.workspace.limits import (
    FILE_TOO_LARGE_DETAIL,
    OFFICE_EXTRACT_MAX_BYTES,
    WORKSPACE_READ_MAX_BYTES,
    is_file_too_large_detail,
    is_liveness_timeout_detail,
)
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

# "成篇" threshold: delete gate + classify_write_kind / prose-append still depend on it.
# file_write whole-file overwrite is allowed (prefer str_replace; soft integrity nudge only).
# Length is advisory only (skill / schema 建议分段) — no hard reject on oversized bodies.
_SUBSTANTIAL_FILE_CHARS = 400


def is_substantial_existing_body(content: str) -> bool:
    """True when ``content`` looks like a finished article / page worth protecting."""
    return len((content or "").strip()) >= _SUBSTANTIAL_FILE_CHARS


def substantial_delete_rejection(path: str, old_chars: int) -> str:
    """User-facing error when ``file_delete`` would wipe a substantial draft."""
    return (
        f"拒绝删除成篇草稿：`{path}` 已有约 {old_chars} 字（阈值 "
        f"{_SUBSTANTIAL_FILE_CHARS} 字）。禁止整篇 delete 后重写长文——"
        "请用 str_replace 局部修订；超长续写须先有短骨架再按节 "
        "file_append / str_replace；预算不够时停在完整章边界并诚实交接，勿推倒重来。"
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
        "请用 str_replace 就地补全（勿再 file_read 回读），或向主管说明需重派。"
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


# Skeleton vs prose (Artifact-first Writing) ---------------------------------
# Explicit outline / website markers always count as skeleton. Otherwise:
# short stubs are skeleton; short + many headings with thin body = skeleton;
# substantial body without those cues = prose (locks same-path append this run).
_SKELETON_SOFT_CHARS = 800
_MD_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(\S.*)$")
_HTML_HEADING_RE = re.compile(r"(?is)<h([1-6])\b[^>]*>(.*?)</h\1>")
_SKELETON_MARKER_RE = re.compile(
    r"<!--\s*(?:SECTION:\S+|OUTLINE)\b",
    re.IGNORECASE,
)


def has_skeleton_markers(content: str) -> bool:
    """True when content carries outline / SECTION placeholders."""
    return bool(_SKELETON_MARKER_RE.search(content or ""))


def extract_title_tree(content: str, *, limit: int = 24) -> list[str]:
    """Cheap heading outline (Markdown ``#`` + HTML ``<hN>``), capped at ``limit``."""
    text = content or ""
    items: list[str] = []
    for match in _MD_HEADING_RE.finditer(text):
        level = len(match.group(1))
        title = match.group(2).strip()
        items.append(f"{'#' * level} {title}")
        if len(items) >= limit:
            return items
    for match in _HTML_HEADING_RE.finditer(text):
        level = int(match.group(1))
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if not title:
            continue
        items.append(f"{'#' * level} {title}")
        if len(items) >= limit:
            break
    return items


def _heading_count(content: str) -> int:
    text = content or ""
    return len(_MD_HEADING_RE.findall(text)) + len(_HTML_HEADING_RE.findall(text))


def _prose_body_chars(content: str) -> int:
    """Rough non-heading body size (strip heading lines / SECTION markers)."""
    text = content or ""
    text = _MD_HEADING_RE.sub("", text)
    text = _HTML_HEADING_RE.sub("", text)
    text = _SKELETON_MARKER_RE.sub("", text)
    return len(text.strip())


def classify_write_kind(content: str) -> Literal["skeleton", "prose"]:
    """Classify a ``file_write`` body as skeleton (append-ok) or prose (append-locked)."""
    text = content or ""
    stripped = text.strip()
    if not stripped:
        return "skeleton"
    if has_skeleton_markers(text):
        return "skeleton"
    if len(stripped) < _SUBSTANTIAL_FILE_CHARS:
        return "skeleton"
    headings = _heading_count(text)
    body = _prose_body_chars(text)
    if (
        len(stripped) <= _SKELETON_SOFT_CHARS
        and headings >= 2
        and body < max(_SUBSTANTIAL_FILE_CHARS, len(stripped) // 2)
    ):
        return "skeleton"
    if headings >= 3 and body < _SUBSTANTIAL_FILE_CHARS:
        return "skeleton"
    return "prose"


def is_skeleton_content(content: str) -> bool:
    """True when ``content`` looks like a fill-in skeleton rather than finished prose."""
    return classify_write_kind(content) == "skeleton"


def content_sha256_short(content: str, *, n: int = 16) -> str:
    """Short hex prefix of SHA-256 over UTF-8 bytes (manifest field)."""
    digest = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
    return digest[:n]


def format_artifact_manifest(
    *,
    path: str,
    content: str,
    bytes_written: int,
    kind: str,
    action: str = "write",
) -> str:
    """Success receipt = artifact manifest（作者以此验真，勿再 file_read 回读正文）。"""
    lines = len((content or "").splitlines())
    tree = extract_title_tree(content)
    tree_block = "\n".join(f"  {t}" for t in tree) if tree else "  （无标题）"
    preview = _tail_preview(content, max_lines=_APPEND_ECHO_LINES, max_chars=_APPEND_ECHO_CHARS)
    verb = "已写入" if action == "write" else "已追加"
    return (
        f"{verb} {bytes_written} 字节到 {path}\n"
        f"【artifact manifest】\n"
        f"path: {path}\n"
        f"kind: {kind}\n"
        f"bytes: {bytes_written}\n"
        f"lines: {lines}\n"
        f"content_sha256: {content_sha256_short(content)}\n"
        f"title_tree:\n{tree_block}\n"
        f"end_preview:\n{preview}\n"
        "【验真】请以本 manifest 确认落盘；优先用 manifest 验真，"
        "勿为空转反复 file_read（同 path 受次数上限约束）。"
    )


def prose_append_rejection(path: str) -> str:
    """Hard reject when appending after a same-run prose ``file_write``."""
    return (
        f"拒绝追加：`{path}` 本 run 已落成篇正文（非骨架）。"
        "短文件应一次 file_write 写完；长交付物应先短骨架再按节 "
        "file_append / str_replace 填空；修订请用 str_replace。"
    )


def _norm_rel_path(path: str) -> str:
    return (path or "").strip().replace("\\", "/")


def _prepare_write_relpath(path: str) -> tuple[str, str]:
    """Sanitize a write path; return ``(actual, rename_note)``.

    ``rename_note`` is a one-line tip when the cleaned path differs from the
    request (empty string when unchanged). Callers append it to success receipts.
    ``/workspace/…`` strip alone does not count as a rename (same as backend
    normalize); only dangerous-char / dossier-flatten changes do.
    """
    from agentcore.workspace._paths import (
        normalize_workspace_path,
        sanitize_write_relpath,
    )

    requested = (path or "").strip()
    if not requested:
        return "", ""
    actual = sanitize_write_relpath(requested)
    baseline = normalize_workspace_path(requested, root_label="workspace")
    if _norm_rel_path(actual) == _norm_rel_path(baseline):
        return actual, ""
    return actual, f"注意：请求路径已清理，实际写入 `{actual}`。"


def write_scope_rejection(context: ToolContext, path: str) -> str | None:
    """Chinese error when ``path`` violates ``context.write_scope``; else ``None``.

    ``project`` — no gate. ``none`` — reject all writes. ``explore_memory`` — path
    must be under ``AgentCore/`` and must not be under ``AgentCore/文档/项目/``.
    """
    scope = getattr(context, "write_scope", "project") or "project"
    if scope == "project":
        return None
    if scope == "none":
        return (
            "当前写范围 write_scope=none：禁止一切写盘。"
            "请改用只读工具，或待主管解除写范围限制后再写。"
        )
    if scope != "explore_memory":
        return None

    from agentcore.workspace.stage_dirs import AGENTCORE_ROOT, PROJECT_DOCS_PREFIX

    norm = _norm_rel_path(path).lstrip("./")
    root_prefix = f"{AGENTCORE_ROOT}/"
    if not (norm == AGENTCORE_ROOT or norm.startswith(root_prefix)):
        return (
            f"冷启动探索写范围仅允许落在 `{AGENTCORE_ROOT}/` 下"
            f"（约定记忆与探索笔记）；拒绝路径 `{path}`。"
            f"请改写到 `{AGENTCORE_ROOT}/文档/research/` 等探索笔记路径，"
            "或待画像写入完成后再写用户工程文件。"
        )
    project_docs = PROJECT_DOCS_PREFIX.rstrip("/")
    if norm == project_docs or norm.startswith(PROJECT_DOCS_PREFIX):
        return (
            f"冷启动探索写范围禁止写入 `{PROJECT_DOCS_PREFIX}`（厚案卷）；"
            f"拒绝路径 `{path}`。请写到 `{AGENTCORE_ROOT}/文档/research/` 等探索笔记，"
            "厚案卷留到探索收尾后。"
        )
    return None


def _reject_write_scope(
    context: ToolContext,
    path: str,
    start: float,
    *,
    event: str = "file_write.scope_rejected",
) -> ToolResult | None:
    """Log + return failed ToolResult when write_scope blocks ``path``."""
    msg = write_scope_rejection(context, path)
    if msg is None:
        return None
    logger.info(event, path=path, write_scope=getattr(context, "write_scope", None))
    return _error(msg, start, contract_failure=True)


def _mark_landed_files(
    context: ToolContext,
    path: str = "",
    *,
    kind: str | None = None,
) -> None:
    """Stamp landed-files gate + Artifact-first path kind (shared mutable dict).

    ``kind="prose"`` locks same-path append. ``kind="skeleton"`` or omitted keeps
    append allowed. Existing ``prose`` is never downgraded.
    First writer of ``path`` is recorded in ``landed_artifact_authors`` (setdefault).
    """
    context.has_landed_files = True
    path_key = _norm_rel_path(path)
    if not path_key:
        return
    # C3: successful I/O → path is no longer declare-only on the ownership ledger.
    coordinator = context.write_coordinator
    if coordinator is not None:
        coordinator.mark_written(path_key)
    author = (context.agent_id or "").strip()
    if author:
        context.landed_artifact_authors.setdefault(path_key, author)
    current = context.landed_artifact_kinds.get(path_key)
    if current == "prose":
        return
    if kind == "prose":
        context.landed_artifact_kinds[path_key] = "prose"
    elif kind == "skeleton":
        context.landed_artifact_kinds[path_key] = "skeleton"
    else:
        context.landed_artifact_kinds.setdefault(path_key, "skeleton")


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
# Artifact-first：写/append 成功回执 = artifact manifest（path/bytes/lines/hash/标题树/末段预览），
# 并硬拒对本 run 已落盘 path 的 body file_read；成篇 prose 后同 path append 亦硬拒。
# 回显有界（行数 + 字符双上限），大文件不炸 token。
_APPEND_ECHO_LINES = 12
_APPEND_ECHO_CHARS = 600
_EDIT_ECHO_CONTEXT = 3
_EDIT_ECHO_MAX_LINES = 24
# str_replace 失败回执：从磁盘带回有界片段（编辑以盘为真源）；不放开通用 file_read 上限。
_EDIT_FAIL_CONTEXT = 3
_EDIT_FAIL_MAX_LINES = 24
_EDIT_FAIL_FUZZY_MAX = 3
_EDIT_FAIL_FUZZY_MIN_RATIO = 0.45
_EDIT_FAIL_OLD_PREVIEW_CHARS = 160


def _region_slice(
    lines: list[str], center_idx0: int, *, context: int, max_lines: int
) -> tuple[int, list[str]]:
    """Return ``(start_line_1based, sliced_lines)`` around ``center_idx0``."""
    half = min(context, max(0, (max_lines - 1) // 2))
    start0 = max(0, center_idx0 - half)
    end0 = min(len(lines), start0 + max_lines)
    start0 = max(0, end0 - max_lines)
    return start0 + 1, lines[start0:end0]


def _old_string_preview(old_string: str) -> str:
    text = old_string.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= _EDIT_FAIL_OLD_PREVIEW_CHARS:
        return text
    return text[:_EDIT_FAIL_OLD_PREVIEW_CHARS] + "…"


def _fuzzy_line_candidates(
    content: str, old_string: str
) -> list[tuple[float, int, list[str]]]:
    """Bounded fuzzy regions near ``old_string`` anchors (score, start_1based, lines)."""
    lines = content.splitlines()
    if not lines:
        return []
    old_lines = [ln for ln in old_string.replace("\r\n", "\n").splitlines() if ln.strip()]
    if not old_lines:
        start, region = _region_slice(
            lines, 0, context=0, max_lines=_EDIT_FAIL_MAX_LINES
        )
        return [(0.0, start, region)]

    scored: list[tuple[float, int]] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        best = max(
            SequenceMatcher(None, line, ol).ratio() for ol in old_lines
        )
        if best >= _EDIT_FAIL_FUZZY_MIN_RATIO:
            scored.append((best, i))
    scored.sort(key=lambda t: (-t[0], t[1]))

    out: list[tuple[float, int, list[str]]] = []
    used: list[int] = []
    min_gap = max(1, _EDIT_FAIL_CONTEXT * 2)
    for score, idx in scored:
        if len(out) >= _EDIT_FAIL_FUZZY_MAX:
            break
        if any(abs(idx - u) < min_gap for u in used):
            continue
        start, region = _region_slice(
            lines,
            idx,
            context=_EDIT_FAIL_CONTEXT,
            max_lines=_EDIT_FAIL_MAX_LINES,
        )
        out.append((score, start, region))
        used.append(idx)

    if not out:
        start, region = _region_slice(
            lines, 0, context=0, max_lines=_EDIT_FAIL_MAX_LINES
        )
        out.append((0.0, start, region))
    return out


def _exact_match_regions(
    content: str, old_string: str, *, max_show: int = _EDIT_FAIL_FUZZY_MAX
) -> list[tuple[int, list[str]]]:
    """First ``max_show`` exact-match regions as ``(start_line_1based, lines)``."""
    lines = content.splitlines()
    if not lines or not old_string:
        return []
    out: list[tuple[int, list[str]]] = []
    start_search = 0
    while len(out) < max_show:
        idx = content.find(old_string, start_search)
        if idx < 0:
            break
        line_idx0 = content[:idx].count("\n")
        start, region = _region_slice(
            lines,
            line_idx0,
            context=_EDIT_FAIL_CONTEXT,
            max_lines=_EDIT_FAIL_MAX_LINES,
        )
        out.append((start, region))
        start_search = idx + max(1, len(old_string))
    return out


def _format_fail_snippet_block(
    *,
    label: str,
    start_line: int,
    region: list[str],
    score: float | None = None,
) -> str:
    score_note = ""
    if score is not None:
        score_note = f"（模糊相似度 {score:.0%}，非精确）"
    header = f"—— {label}{score_note} · 约第 {start_line} 行起 ——"
    body = _format_numbered_lines(region, start_line)
    return f"{header}\n{body}" if body else header


async def _assemble_str_replace_fail_receipt(
    context: ToolContext,
    rel_path: str,
    old_string: str,
    *,
    kind: Literal["no_match", "ambiguous"],
    match_count: int | None = None,
) -> str:
    """Disk-backed failure receipt for ``str_replace`` (bounded snippets; no sticky re-read).

    Backend still raises ``NoMatch`` / ``AmbiguousMatch``; this only enriches the tool
    error so the model can re-anchor from disk instead of inventing a skeleton rewrite.
    """
    if kind == "no_match":
        head = (
            f"在 {rel_path} 中找不到 old_string；它必须与磁盘文件完全一致，"
            "包括空白与缩进。"
        )
    else:
        head = (
            f"old_string 在 {rel_path} 中不唯一（匹配 {match_count} 处）。请补充"
            "更多上下文以锁定单一片段，或设置 replace_all=true。"
        )
    head += (
        f"\n你提供的 old_string 预览：\n```\n{_old_string_preview(old_string)}\n```"
        "\n以下为磁盘原文片段（真源；标明非精确的仅供锚定，勿当已匹配）："
    )

    try:
        content = await context.backend.read(rel_path)
    except WorkspaceError as e:
        return (
            f"{head}\n（无法读取磁盘：{e}）\n"
            "请 escalate 或改用其它路径；优先对照盘文再 str_replace，"
            "确需整盖须写出完整正文（勿残缺骨架交差）。"
        )

    blocks: list[str] = []
    if kind == "ambiguous" and old_string:
        for i, (start, region) in enumerate(
            _exact_match_regions(content, old_string), start=1
        ):
            blocks.append(
                _format_fail_snippet_block(
                    label=f"精确命中 #{i}",
                    start_line=start,
                    region=region,
                )
            )
        if match_count is not None and match_count > len(blocks):
            blocks.append(f"（另有 {match_count - len(blocks)} 处未列出）")
    else:
        for i, (score, start, region) in enumerate(
            _fuzzy_line_candidates(content, old_string), start=1
        ):
            label = "文件开头" if score == 0.0 and i == 1 else f"候选 #{i}"
            blocks.append(
                _format_fail_snippet_block(
                    label=label,
                    start_line=start,
                    region=region,
                    score=None if score == 0.0 else score,
                )
            )

    guidance = (
        "\n请对照上方盘片段重写精确 old_string 后再 str_replace；"
        "确需整文件覆盖可用 file_write（须完整正文，勿残缺骨架交差）；仍对不上则 escalate。"
    )
    return head + "\n\n" + "\n\n".join(blocks) + guidance


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


def _error(
    error: str,
    start: float,
    *,
    contract_failure: bool = False,
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    """Build a failed ToolResult with elapsed timing.

    ``contract_failure`` marks a self-correctable argument-contract rejection (e.g. a
    concurrent-write collision the model fixes by renaming) so the run-scoped tool
    circuit breaker skips normal failure tallies — see
    :class:`~agentcore.tools.protocol.ToolResult`. Explicit ``retire_tools`` in
    ``metadata`` still hard-disables named tools (e.g. workspace channel dead).
    """
    return ToolResult(
        tool_call_id="",
        success=False,
        output="",
        error=error,
        duration_ms=int((time.monotonic() - start) * 1000),
        contract_failure=contract_failure,
        metadata=dict(metadata or {}),
    )


def _file_too_large_error(path: str, start: float) -> ToolResult:
    """Capacity contract: oversized whole-file read (cloud + local share detail)."""
    max_mib = WORKSPACE_READ_MAX_BYTES // (1024 * 1024)
    return _error(
        (
            f"`{path}` {FILE_TOO_LARGE_DETAIL}（上限 {max_mib} MiB）。"
            "请改用 offset/limit 精读、grep 定位后局部读，或请用户提供更小片段 / 先转文本；"
            "禁止原样重试整文件读取。"
        ),
        start,
        contract_failure=True,
        metadata={"capacity_contract": "bytes"},
    )


def _office_extract_budget_error(path: str, size: int, start: float) -> ToolResult:
    """Capacity contract: Office/PDF extract cost pre-check (avoid burning liveness)."""
    max_mib = OFFICE_EXTRACT_MAX_BYTES // (1024 * 1024)
    size_mib = max(1, (size + 1024 * 1024 - 1) // (1024 * 1024))
    return _error(
        (
            f"`{path}` 体积约 {size_mib} MiB，超过透明抽取预算（{max_mib} MiB）。"
            "请请用户提供更小文件、先转 `.md`/文本后再 file_read，或改用已有 "
            "attachments 旁路摘要；禁止原样重试抽取。"
        ),
        start,
        contract_failure=True,
        metadata={"capacity_contract": "extract_bytes"},
    )


def _liveness_workspace_error(detail: str, start: float) -> ToolResult:
    """Liveness hang on the local workspace channel (permanent first-fail retire)."""
    from agentcore.workspace.limits import (
        WORKSPACE_CHANNEL_DEAD_RETIRE_STEER,
        WORKSPACE_CHANNEL_DEAD_RETIRE_TOOLS,
    )

    return _error(
        (
            f"本地工作区通道活性挂起（无响应）：{detail}。"
            "这不是文件过大或参数合同失败——"
            f"{WORKSPACE_CHANNEL_DEAD_RETIRE_STEER}"
        ),
        start,
        metadata={
            "liveness_timeout": True,
            "timeout_layer": "channel",
            "error_class": "permanent",
            "workspace_channel_dead": True,
            "retire_tools": list(WORKSPACE_CHANNEL_DEAD_RETIRE_TOOLS),
            "retire_message": WORKSPACE_CHANNEL_DEAD_RETIRE_STEER,
        },
    )


def _map_workspace_read_error(exc: WorkspaceError, *, path: str, start: float) -> ToolResult:
    """Map backend read failures to capacity vs liveness vs generic I/O."""
    detail = str(exc)
    if is_file_too_large_detail(detail):
        return _file_too_large_error(path, start)
    if is_liveness_timeout_detail(detail):
        return _liveness_workspace_error(detail, start)
    return _error(f"读取文件失败：{exc}", start)


def _file_read_path_ceiling_error(error: str, start: float) -> ToolResult:
    """Reject a same-path over-cap read (path-scoped; does not retire ``file_read``)."""
    return _error(
        error,
        start,
        contract_failure=True,
    )


def _outside_workspace_msg(path: str, *, location: str | None = None) -> str:
    """Actionable OutsideWorkspace text.

    Path contract lives in ``normalize_workspace_path`` / ``resolve_safe_path``;
    this message only points at remaining rejects (true out-of-root absolutes).

    On cloud (``location=server``), point at open_local_project / bind_local_folder
    by intent when the model was reaching for the user's machine.
    """
    relative_fix = (
        "请使用工作区相对路径（如 AgentCore/文档/research/report.md；"
        "`.` 或裸 `/` 表示整仓）；勿使用工作区外的绝对路径（如 /etc、盘符）。"
    )
    if location == "server":
        return (
            f"路径 '{path}' 超出了工作区范围。"
            "若要把该本机目录当【本地项目】打开：桌面在线时立即发 ask_user 卡"
            "（action=open_local_project；新建会话，不改本会话 folder_id）；"
            "若本会话仅需本机执行环境：action=bind_local_folder（≠打开项目）；"
            "勿用纯文本询问。"
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
        from agentcore.workspace.write_claims import (
            lookup_owner_status,
            ownership_conflict_message,
        )

        on_write_conflict(
            path=rel_path,
            run_id=context.run_id,
            owner_run_id=owner,
        )
        ownership_kind = "written" if coordinator.is_written(rel_path) else "declared"
        owner_role, owner_status = lookup_owner_status(
            owner, execution_id=context.execution_id
        )
        return (
            _error(
                ownership_conflict_message(
                    rel_path,
                    owner,
                    owner_role=owner_role,
                    ownership_kind=ownership_kind,
                    owner_status=owner_status,
                ),
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
    """案卷 ``research/`` 落盘时若正文无 ``#rN``，用本 worker 台账条目补脚注（一层兜底）。"""
    from agentcore.workspace.stage_dirs import RESEARCH_PREFIX

    norm = (rel_path or "").replace("\\", "/").lstrip("./")
    if not norm.startswith(RESEARCH_PREFIX) or not norm.endswith(".md"):
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


def _format_extracted_read(
    text: str,
    *,
    offset: int | None,
    limit: int | None,
) -> str:
    """Apply file_read offset/limit to extracted (or sidecar) text lines."""
    use_range = offset is not None or limit is not None
    if not use_range:
        return _truncate_content_lines(
            text if text.endswith("\n") or not text else text + "\n",
            _DEFAULT_READ_LINES,
        )

    lines = text.splitlines()
    total = len(lines)
    eff_offset = int(offset) if offset is not None else 1
    eff_limit = int(limit) if limit is not None else _DEFAULT_READ_LINES
    start_idx = max(0, eff_offset - 1)
    if start_idx >= total:
        return f"（第 {eff_offset}–{eff_offset - 1} 行，共 {total} 行）"
    selected = lines[start_idx : start_idx + eff_limit]
    start_line = start_idx + 1
    end_line = start_idx + len(selected)
    body = _format_numbered_lines(selected, start_line)
    footer = f"\n\n（第 {start_line}–{end_line} 行，共 {total} 行）"
    return body + footer if body else footer.lstrip()


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
                "Office/PDF（docx/pdf/pptx/odt/rtf）自动抽取文本；表格（xlsx/csv 等）请用 "
                "code_execute。"
                "宜在 grep / code_search 命中后再读；优先传 offset/limit 精读片段，"
                "禁止无目标地整目录逐文件通读。"
                "同一相对路径本 run 有成功读取次数上限（整读与 offset/limit 合计）；"
                "触顶后仅拒绝该路径，其它文件仍可 file_read；须基于已有正文写作 / "
                "handoff，勿空转重读同一文件。"
                "已落盘产物优先以写/append 回执中的 artifact manifest 验真。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "工作区相对 POSIX 文件路径（`.`=根；`/<根标签>/…` 与裸 `/`、"
                            "`\\` 视为根；其它绝对路径如 /etc、盘符拒绝）"
                        ),
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
                    return _file_read_path_ceiling_error(
                        (
                            f"已多次读取 `{path_key}`（本 run 上限 "
                            f"{FILE_READ_SAME_PATH_MAX} 次）。正文已在对话中，勿再读此文件；"
                            "可换其它文件，或基于已有正文落盘 / handoff。"
                        ),
                        start,
                    )
                if remaining <= 0:
                    return _file_read_path_ceiling_error(
                        (
                            f"已多次读取 `{path_key}`，且上下文中的正文已被清理、"
                            "再读次数已用尽。请依据清理摘要推进，或读取其它文件 / 落盘；"
                            "勿空转重复 file_read 此路径。"
                        ),
                        start,
                    )
                using_reread = True

        ext = extension_of(path_key or rel_path)
        if ext in SKIP_EXTENSIONS:
            return _error(
                (
                    f"`{path_key or rel_path}` 是表格/分隔数据文件，file_read 不自动抽文本；"
                    "请用 code_execute（如 openpyxl / pandas）按工作区相对路径解析。"
                ),
                start,
            )

        if ext in MARKITDOWN_EXTENSIONS:
            return await self._read_office_or_pdf(
                rel_path,
                path_key=path_key,
                offset=offset,
                limit=limit,
                using_reread=using_reread,
                start=start,
                context=context,
            )

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
            return _map_workspace_read_error(e, path=path_key or rel_path, start=start)

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

    async def _read_office_or_pdf(
        self,
        rel_path: str,
        *,
        path_key: str,
        offset: int | None,
        limit: int | None,
        using_reread: bool,
        start: float,
        context: ToolContext,
    ) -> ToolResult:
        """Transparent office/PDF extract via markitdown (no default ``*.md`` write)."""
        sidecar = parsed_copy_path(rel_path.replace("\\", "/"))
        text: str | None = None

        try:
            sidecar_text = await context.backend.read(sidecar)
            if (sidecar_text or "").strip():
                text = sidecar_text
        except PathNotFound:
            pass
        except OutsideWorkspace:
            return _error(
                _outside_workspace_msg(rel_path, location=context.backend.location),
                start,
            )
        except NotAFile:
            pass
        except WorkspaceError:
            pass

        if text is None:
            try:
                data = await context.backend.read_bytes(rel_path)
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
                return _map_workspace_read_error(e, path=path_key or rel_path, start=start)

            if len(data) > OFFICE_EXTRACT_MAX_BYTES:
                return _office_extract_budget_error(
                    path_key or rel_path, len(data), start
                )

            extracted = await extract_office_bytes(data, ext=extension_of(path_key or rel_path))
            if extracted.status == ParseStatus.FAILED:
                return _error(
                    (
                        f"无法从 `{path_key or rel_path}` 抽取文本"
                        f"（{extracted.detail or 'convert failed'}）。"
                        "若缺 markitdown 依赖或文件损坏，请告知用户；"
                        "不要改用 code_execute 硬解 Office/PDF。"
                    ),
                    start,
                )
            if extracted.status == ParseStatus.SKIPPED:
                return _error(
                    f"`{path_key or rel_path}` 不支持透明文本抽取。",
                    start,
                )
            # OK or SCANNED — both carry honest text (scan notice is not empty success).
            text = extracted.text
            if extracted.status == ParseStatus.SCANNED and not (text or "").strip():
                return _error(
                    f"`{path_key or rel_path}` 看起来是扫描件且无可抽文本层（无 OCR）。",
                    start,
                )

        assert text is not None
        output = _format_extracted_read(text, offset=offset, limit=limit)
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
                "已有文件。用它来【新建】文件；修订时【优先】str_replace 局部改，"
                "整文件覆盖亦允许（结构性换稿 / 确需整盖时可用）。"
                "【Artifact-first】短文件可一次写完；长交付物（综述/报告/长文/"
                "整页 HTML）【建议】分段——先短骨架（标题/锚点/"
                "`<!-- SECTION: -->`）再按节 file_append 或 str_replace 填空；"
                "超长正文一次写亦不硬拒，仍建议分段以降低截断风险。"
                "成功回执为 artifact manifest（优先以此验真；反复 file_read "
                "受同 path 次数上限约束）。"
                "【修订已有成品】优先 str_replace；整盖允许但勿惰性省略中段"
                "（反例：「……（中间省略，已保留首尾）……」会残缺交付——"
                "省略/字数骤降仅软提示，不拦截写入）。"
                "补丁失败（str_replace NoMatch）或读不到原文 ≠ 用残缺骨架交差；"
                "应对照失败回执中的盘片段再改，或 escalate；确需整盖须写出完整正文。"
                "【代码完整性】对 .ts/.tsx/.js 等：无 SECTION 骨架标记时，"
                "括号结构不完整或含省略标记 → 硬拒绝（防截断类缺 `}`）。"
                "只改一部分优先 str_replace；骨架填空才用 file_append。"
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
                            "要写入的内容。短文件一次写完；长交付物建议短骨架 + "
                            "按节填空（不硬拒整篇一次写）。"
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
        requested_path = arguments.get("path", "")
        content = arguments.get("content", "")

        # A missing/empty path resolves to the workspace root (a directory); writing
        # onto it raises a cryptic OS error (Permission denied / IsADirectory) that
        # leaks the absolute server path and gives the model nothing to act on. Fail
        # fast with the required-arg message instead (parity with str_replace/move).
        if not requested_path:
            return _error("path 不能为空：请提供工作区内的相对文件路径（如 report.md）", start)

        rel_path, rename_note = _prepare_write_relpath(requested_path)

        scope_denied = _reject_write_scope(
            context, rel_path, start, event="file_write.scope_rejected"
        )
        if scope_denied is not None:
            return scope_denied

        # 并行写隔离·硬约束 (C3): refuse overwrite when another run owns the path.
        # Claimed BEFORE the awaited write; ancestor handoff still allowed.
        denied, release_on_fail = _claim_write_path(
            context, rel_path, event="file_write.collision", start=start
        )
        if denied is not None:
            return denied
        coordinator = context.write_coordinator

        # 幕1 案卷落盘锚：AgentCore/文档/research/ 下若正文无 #rN，
        # 用本回合台账条目写脚注（一层兜底）。
        write_content = _maybe_inject_research_ledger_anchors(
            rel_path, content, context
        )

        # Pre-read for overwrite integrity soft nudge (whole-file overwrite allowed).
        old_content: str | None = None
        try:
            old_content = await context.backend.read(rel_path)
        except PathNotFound:
            old_content = None
        except WorkspaceError:
            old_content = None

        # 代码落盘完整性闸 (D1)：括号截断 / 省略标记硬拒；SECTION 骨架豁免。
        if is_brace_code_path(rel_path):
            if has_omission_marker(write_content):
                logger.info(
                    "file_write.code_integrity_rejected",
                    path=rel_path,
                    reason="omission",
                )
                if coordinator is not None and release_on_fail:
                    coordinator.release(rel_path, context.run_id)
                return _error(
                    code_omission_rejection(rel_path),
                    start,
                    contract_failure=True,
                )
            if not has_skeleton_markers(write_content):
                struct_err = code_structure_rejection(rel_path, write_content)
                if struct_err is not None:
                    logger.info(
                        "file_write.code_integrity_rejected",
                        path=rel_path,
                        reason="structure",
                    )
                    if coordinator is not None and release_on_fail:
                        coordinator.release(rel_path, context.run_id)
                    return _error(struct_err, start, contract_failure=True)

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
        kind = classify_write_kind(write_content)
        path_key = _norm_rel_path(rel_path)
        output = format_artifact_manifest(
            path=rel_path,
            content=write_content,
            bytes_written=written,
            kind=kind,
            action="write",
        )
        if rename_note:
            output = f"{output}\n{rename_note}"
        if anchor_note:
            output += anchor_note
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
        _mark_landed_files(context, path_key, kind=kind)
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
                "仅用于骨架填空 / 建站 SECTION 壳：短骨架或 `<!-- SECTION: -->` 落盘后"
                "按节追加（单次建议一节为宜，不硬拒字数）。禁止对「本 run 已 "
                "file_write 成篇正文」再 append——"
                "短文件应一次写完，长交付物宜先骨架再分段填空；修订用 str_replace。"
                "成功回执为 artifact manifest（优先以此验真；反复 file_read "
                "受同 path 次数上限约束）。"
                "若要【整体覆盖】短文件，用 file_write；改中间某段用 "
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
                            "要追加到文件末尾的内容（一节/一段为宜，不硬拒字数；"
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
        requested_path = arguments.get("path", "")
        content = arguments.get("content", "")

        if not requested_path:
            return _error("path 不能为空：请提供工作区内的相对文件路径（如 report.md）", start)

        rel_path, rename_note = _prepare_write_relpath(requested_path)

        scope_denied = _reject_write_scope(
            context, rel_path, start, event="file_append.scope_rejected"
        )
        if scope_denied is not None:
            return scope_denied

        path_key = _norm_rel_path(rel_path)
        if context.landed_artifact_kinds.get(path_key) == "prose":
            return _error(
                prose_append_rejection(rel_path),
                start,
                contract_failure=True,
            )

        denied, release_on_fail = _claim_write_path(
            context, rel_path, event="file_append.collision", start=start
        )
        if denied is not None:
            return denied
        coordinator = context.write_coordinator

        # Pre-read: missing → create-via-append (allowed); existing skeleton → fill-in.
        old_content: str | None = None
        try:
            old_content = await context.backend.read(rel_path)
        except PathNotFound:
            old_content = None
        except WorkspaceError:
            old_content = None

        # Disk already looks like finished prose and this run wrote it as prose
        # is handled above. If disk is prose but not locked this run (扩写 / 他 run
        # 骨架)，仍放行。若本 run 未登记且盘上已是成篇、又无骨架标记——仍放行扩写。

        # 代码落盘完整性闸 (D1)：追加后的合并正文也必须结构完整（骨架豁免）。
        merged_preview = (old_content or "") + (content or "")
        if is_brace_code_path(rel_path):
            if has_omission_marker(content or ""):
                if coordinator is not None and release_on_fail:
                    coordinator.release(rel_path, context.run_id)
                return _error(
                    code_omission_rejection(rel_path),
                    start,
                    contract_failure=True,
                )
            skeleton_ok = has_skeleton_markers(merged_preview) or has_skeleton_markers(
                old_content or ""
            )
            if not skeleton_ok:
                struct_err = code_structure_rejection(rel_path, merged_preview)
                if struct_err is not None:
                    logger.info(
                        "file_append.code_integrity_rejected",
                        path=rel_path,
                        reason="structure",
                    )
                    if coordinator is not None and release_on_fail:
                        coordinator.release(rel_path, context.run_id)
                    return _error(struct_err, start, contract_failure=True)

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

        try:
            merged = await context.backend.read(rel_path)
        except WorkspaceError:
            merged = (old_content or "") + (content or "")

        if old_content is None:
            # Created via append: classify the new body (skeleton fill-in vs prose dump).
            kind = classify_write_kind(merged)
        elif is_skeleton_content(old_content) or has_skeleton_markers(old_content):
            kind = "skeleton"
        elif path_key not in context.landed_artifact_kinds:
            # Pre-existing non-skeleton (扩写): land for read-reject, keep append-ok.
            kind = "skeleton"
        else:
            kind = context.landed_artifact_kinds.get(path_key) or "skeleton"

        output = format_artifact_manifest(
            path=rel_path,
            content=merged,
            bytes_written=appended,
            kind=kind,
            action="append",
        )
        if rename_note:
            output = f"{output}\n{rename_note}"
        _mark_landed_files(context, path_key, kind=kind)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
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
                        "description": (
                            "工作区相对 POSIX 目录（默认 `.`=整仓；`/<根标签>/…` 与裸 `/`、"
                            "`\\` 视为根；其它绝对路径拒绝）"
                        ),
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
                "通过替换【完全精确匹配的文本片段】来编辑已有文件。改文件时【优先】"
                "用它而非 file_write：它只重写匹配到的片段，因此对大文件安全、也"
                "不会误伤无关内容；整文件覆盖亦允许（结构性换稿时）。在 old_string "
                "里放足够的上下文，确保在文件中【唯一匹配一次】（包括空白、缩进与换行）。"
                "若 old_string 不存在、或匹配多于一次（除非 replace_all=true），则失败；"
                "失败回执会附带磁盘原文有界片段（模糊候选会标明非精确）——以盘文为真源"
                "重锚再改；确需整盖可用 file_write（须完整正文，勿残缺骨架交差）。"
                "要新建文件请改用 file_write。"
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
                        "minLength": 1,
                        "description": (
                            "要替换的精确文本（不可为空），需带足够的上下文以在文件中唯一。"
                        ),
                    },
                    "new_string": {
                        "type": "string",
                        "description": (
                            "替换后的文本（必须与 old_string 不同；"
                            "单次替换建议一节为宜，不硬拒字数）。"
                        ),
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

        # 参数契约拒绝：空 / 无改动的 old_string 是零成本可修正打回，须标
        # contract_failure，否则连续空参会烧穿 run 级工具熔断（warn→disable）。
        if not old_string:
            return _error(
                "old_string 不能为空：请填入磁盘文件中要替换的精确原文"
                "（含足够上下文以保证唯一匹配），不要传空字符串",
                start,
                contract_failure=True,
            )
        if old_string == new_string:
            return _error(
                "old_string 与 new_string 相同，没有需要改动的内容",
                start,
                contract_failure=True,
            )

        if not rel_path:
            return _error("path 不能为空：请提供工作区内的相对文件路径", start)

        rel_path, rename_note = _prepare_write_relpath(rel_path)

        scope_denied = _reject_write_scope(
            context, rel_path, start, event="str_replace.scope_rejected"
        )
        if scope_denied is not None:
            return scope_denied

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
            # 失败回执自带有界盘片段 → 不加 sticky「补丁再读」，勿放开通用 file_read 上限。
            receipt = await _assemble_str_replace_fail_receipt(
                context, rel_path, old_string, kind="no_match"
            )
            return _error(receipt, start)
        except AmbiguousMatch as e:
            if coordinator is not None and release_on_fail:
                coordinator.release(rel_path, context.run_id)
            receipt = await _assemble_str_replace_fail_receipt(
                context,
                rel_path,
                old_string,
                kind="ambiguous",
                match_count=e.count,
            )
            return _error(receipt, start)
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
        _mark_landed_files(context, rel_path)
        rename_suffix = f"。{rename_note}" if rename_note else ""
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已在 {rel_path} 替换 {outcome.count} 处{loc}{echo}{rename_suffix}",
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
        requested_path = (arguments.get("path") or "").strip()
        section_raw = arguments.get("section", "")
        content_arg = arguments.get("content")
        from_file = (arguments.get("from_file") or "").strip()

        if not requested_path:
            return _error("path 不能为空：请提供含 SECTION 标记的相对路径", start)
        if content_arg is not None and from_file:
            return _error("content 与 from_file 只能提供其一", start)
        if content_arg is None and not from_file:
            return _error("须提供 content 或 from_file（分区 HTML 正文来源）", start)

        rel_path, rename_note = _prepare_write_relpath(requested_path)

        scope_denied = _reject_write_scope(
            context, rel_path, start, event="file_write.scope_rejected"
        )
        if scope_denied is not None:
            return scope_denied

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
            unchanged = f"SECTION:{slug} 在 {rel_path} 已是目标正文，无需改动"
            if rename_note:
                unchanged = f"{unchanged}。{rename_note}"
            return ToolResult(
                tool_call_id="",
                success=True,
                output=unchanged,
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

        _mark_landed_files(context, rel_path)
        src = f"（来自 `{from_file}`）" if from_file else ""
        rename_suffix = f"。{rename_note}" if rename_note else ""
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已将 SECTION:{slug} 写入 {rel_path}{src}{rename_suffix}",
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
                "（AgentCore/trash，保留还原所需信息）。仅当 permanent=true 时"
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

        scope_denied = _reject_write_scope(
            context, rel_path, start, event="file_write.scope_rejected"
        )
        if scope_denied is not None:
            return scope_denied

        denied, release_on_fail = _claim_write_path(
            context, rel_path, event="file_delete.collision", start=start
        )
        if denied is not None:
            return denied
        coordinator = context.write_coordinator

        # 成篇质量：禁止「删长文 → 整篇重写」烧预算（delete 闸）；
        # file_write 整盖已允许，仅软 integrity nudge。
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
                "（本地通道→系统回收站；云端/sidecar→工作区 AgentCore/trash）"
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
        requested_dest = arguments.get("destination", "")

        if not source or not requested_dest:
            return _error("'source' 与 'destination' 均为必填", start)

        destination, rename_note = _prepare_write_relpath(requested_dest)

        if source == destination:
            return _error("source 与 destination 相同，无需移动", start)

        for p in (source, destination):
            scope_denied = _reject_write_scope(
                context, p, start, event="file_write.scope_rejected"
            )
            if scope_denied is not None:
                return scope_denied

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

        output = f"已把 {source} 移动到 {destination}"
        if rename_note:
            output = f"{output}。{rename_note}"
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
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
        requested_dest = arguments.get("destination", "")

        if not source or not requested_dest:
            return _error("'source' 与 'destination' 均为必填", start)

        destination, rename_note = _prepare_write_relpath(requested_dest)

        if source == destination:
            return _error("source 与 destination 相同，无需复制", start)

        scope_denied = _reject_write_scope(
            context, destination, start, event="file_write.scope_rejected"
        )
        if scope_denied is not None:
            return scope_denied

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

        output = f"已把 {source} 复制到 {destination}"
        if rename_note:
            output = f"{output}。{rename_note}"
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
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

        scope_denied = _reject_write_scope(
            context, rel_path, start, event="file_write.scope_rejected"
        )
        if scope_denied is not None:
            return scope_denied

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
            scope_err = write_scope_rejection(context, path)
            if scope_err is not None:
                logger.info(
                    "file_write.scope_rejected",
                    path=path,
                    write_scope=getattr(context, "write_scope", None),
                    op=op,
                )
                return "fail", scope_err
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
            scope_err = write_scope_rejection(context, path)
            if scope_err is not None:
                logger.info(
                    "file_write.scope_rejected",
                    path=path,
                    write_scope=getattr(context, "write_scope", None),
                    op=op,
                )
                return "fail", scope_err
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
        for p in (source, destination) if op == "move" else (destination,):
            scope_err = write_scope_rejection(context, p)
            if scope_err is not None:
                logger.info(
                    "file_write.scope_rejected",
                    path=p,
                    write_scope=getattr(context, "write_scope", None),
                    op=op,
                )
                return "fail", scope_err
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
