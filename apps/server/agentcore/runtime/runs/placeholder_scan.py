"""Deterministic placeholder / unverified-content scan for file deliverables.

Catches shipping placeholders that slipped past human acceptance (GEO-style accidents:
``400-XXX-XXXX``, self-notes like「示例数据（发布前核实）」). Pure functions — no I/O.

**Hard signals** (fail the contract gate when found in content / marketing files):
phone-style ``XXX`` segments, ``PLACEHOLDER``, ``TODO`` / ``FIXME`` as body markers,
``[占位]``, lorem ipsum, etc.

**Soft signals** (warn only — never fail): self-annotations such as「示例数据」「待核实」
「仅供参考的估算」. Worker / CEO decide whether to fix or accept.

**Code files** (``.py`` / ``.ts`` / …): TODO / XXX / PLACEHOLDER-style hard patterns are
exempt (normal coding habit). Soft signals are also skipped in code to prefer low
false positives. Distinct content placeholders in HTML / Markdown / plain text still fail.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# Cap listed hits so retry / reminder prompts stay actionable.
_MAX_HITS_LISTED = 12
_SNIPPET_CHARS = 48

# Content / marketing surfaces — hard + soft both apply.
_CONTENT_EXTS = frozenset(
    {
        ".html",
        ".htm",
        ".md",
        ".markdown",
        ".mdx",
        ".txt",
        ".rst",
        ".adoc",
        ".csv",
        ".xml",
        ".svg",
    }
)
# Code surfaces — hard TODO/XXX habits exempt; soft skipped (防误报).
_CODE_EXTS = frozenset(
    {
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".vue",
        ".svelte",
        ".sql",
        ".sh",
        ".bash",
        ".ps1",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".json",
        ".jsonc",
    }
)

# (label, compiled pattern) — hard: placeholder tokens that must not ship as product.
_HARD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "占位电话段",
        re.compile(
            r"(?:"
            r"400[-\s]?XXX[-\s]?XXXX"
            r"|1[-\s]?800[-\s]?XXX[-\s]?XXXX"
            r"|\b0\d{2,3}[-\s]?XXXX[-\s]?XXXX\b"
            r"|\b\d{3}[-\s]?XXX[-\s]?\d{4}\b"
            r"|\bXXX[-\s]?XXXX\b"
            r")",
            re.IGNORECASE,
        ),
    ),
    (
        "PLACEHOLDER",
        re.compile(r"\bPLACEHOLDER\b", re.IGNORECASE),
    ),
    (
        "TODO/FIXME",
        re.compile(r"\b(?:TODO|FIXME)\b"),
    ),
    (
        "[占位]",
        re.compile(r"\[占位\]|【占位】"),
    ),
    (
        "lorem ipsum",
        re.compile(r"\blorem\s+ipsum\b", re.IGNORECASE),
    ),
    (
        "示例占位标记",
        re.compile(r"(?:TBD|FIXME_ME|REPLACE_ME|YOUR_\w+_HERE)", re.IGNORECASE),
    ),
)

# Soft: author self-notes that content is illustrative / unverified — warn only.
_SOFT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("示例数据", re.compile(r"示例数据")),
    ("示例证言", re.compile(r"示例(?:客户)?证言|客户证言为示例")),
    ("待核实", re.compile(r"待核实|发布前核实|上线前核实")),
    ("仅供参考", re.compile(r"仅供参考(?:的估算)?|估算[，,]?\s*仅供参考")),
    ("虚构/示意", re.compile(r"虚构(?:数据|指标|内容)?|示意(?:性)?(?:数据|内容)?")),
)


@dataclass(frozen=True)
class PlaceholderHit:
    """One pattern match with path + short snippet for feedback."""

    path: str
    kind: str  # hard | soft
    label: str
    snippet: str


@dataclass
class PlaceholderScanResult:
    """Hard failures + soft warnings from one artifact batch."""

    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hits: list[PlaceholderHit] = field(default_factory=list)


def _ext(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def is_content_deliverable_path(path: str) -> bool:
    """True when ``path`` is a content / marketing surface (HTML, Markdown, …)."""
    return _ext(path) in _CONTENT_EXTS


def is_code_deliverable_path(path: str) -> bool:
    """True when ``path`` is a code / config surface (TODO/XXX habits exempt)."""
    return _ext(path) in _CODE_EXTS


def needs_placeholder_scan(paths: Iterable[str]) -> bool:
    """True when any landed path is a content surface worth scanning."""
    return any(is_content_deliverable_path(p) for p in paths if p)


def _normalize_scan_path(path: str) -> str:
    raw = path.replace("\\", "/").strip().lstrip("./")
    return raw


def path_matches_placeholder_exempt(path: str, exempt_patterns: Iterable[str]) -> bool:
    """True when ``path`` matches any exempt pattern (exact or suffix path segment)."""
    norm = _normalize_scan_path(path)
    if not norm:
        return False
    for pattern in exempt_patterns:
        if not pattern:
            continue
        pat = _normalize_scan_path(pattern)
        if not pat:
            continue
        if norm == pat or norm.endswith("/" + pat):
            return True
        if pat.endswith("/") and norm.startswith(pat):
            return True
    return False


def _snippet_at(text: str, start: int, end: int) -> str:
    lo = max(0, start - 8)
    hi = min(len(text), end + 8)
    chunk = text[lo:hi].replace("\n", " ").strip()
    if len(chunk) > _SNIPPET_CHARS:
        chunk = chunk[: _SNIPPET_CHARS - 1] + "…"
    return chunk


# HTML ``placeholder=`` / CSS ``::placeholder`` / JS ``.placeholder`` are legitimate UI
# syntax — mask identifier spans (length-preserving) so ``\bPLACEHOLDER\b`` does not fire;
# quoted attribute *values* stay scannable for real hard signals (e.g. 400-XXX-XXXX).
_HTML_PLACEHOLDER_ATTR_QUOTED = re.compile(
    r'\b(placeholder)(\s*=\s*(["\'])(?:\\.|(?!\3).)*?\3)',
    re.IGNORECASE | re.DOTALL,
)
_HTML_PLACEHOLDER_ATTR_UNQUOTED = re.compile(
    r"\b(placeholder)(\s*=\s*[^\s/>]+)",
    re.IGNORECASE,
)
_CSS_PLACEHOLDER_PSEUDO = re.compile(r"::(placeholder)\b", re.IGNORECASE)
_DOT_PLACEHOLDER = re.compile(
    r"\.(placeholder)((?:[-_][\w-]+)?)",
    re.IGNORECASE,
)
_JS_PLACEHOLDER_KEY = re.compile(r"\b(placeholder)(\s*:)", re.IGNORECASE)
_DOM_ATTR_PLACEHOLDER_NAME = re.compile(
    r"((?:set|get|remove)Attribute\s*\(\s*(['\"]))(placeholder)(\2)",
    re.IGNORECASE,
)


def _mask_ui_placeholder_syntax(text: str) -> str:
    """Return ``text`` with UI ``placeholder`` syntax identifiers blanked out."""
    if not text:
        return text

    masked = _HTML_PLACEHOLDER_ATTR_QUOTED.sub(
        lambda m: ("_" * len(m.group(1))) + m.group(2),
        text,
    )
    masked = _HTML_PLACEHOLDER_ATTR_UNQUOTED.sub(
        lambda m: ("_" * len(m.group(1))) + m.group(2),
        masked,
    )
    masked = _CSS_PLACEHOLDER_PSEUDO.sub(
        lambda m: "::" + ("_" * len(m.group(1))),
        masked,
    )
    masked = _DOT_PLACEHOLDER.sub(
        lambda m: "." + ("_" * len(m.group(1))) + m.group(2),
        masked,
    )
    masked = _JS_PLACEHOLDER_KEY.sub(
        lambda m: ("_" * len(m.group(1))) + m.group(2),
        masked,
    )
    masked = _DOM_ATTR_PLACEHOLDER_NAME.sub(
        lambda m: m.group(1) + ("_" * len(m.group(3))) + m.group(4),
        masked,
    )
    return masked


# "禁止 lorem ipsum / 禁 lorem …" in design rules must not fail the gate.
_LOREM_PROHIBITION_CONTEXT = re.compile(
    r"(?:禁止|严禁|勿|不要|别|禁)\s*.{0,12}lorem",
    re.IGNORECASE,
)


def _is_lorem_prohibition_mention(text: str, start: int, end: int) -> bool:
    """True when ``lorem ipsum`` appears only as a blacklist restatement."""
    window = text[max(0, start - 16) : min(len(text), end + 8)]
    return bool(_LOREM_PROHIBITION_CONTEXT.search(window))


def _collect_hits(
    path: str,
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    *,
    kind: str,
) -> list[PlaceholderHit]:
    hits: list[PlaceholderHit] = []
    seen: set[tuple[str, str]] = set()
    scan_text = _mask_ui_placeholder_syntax(text or "")
    for label, pat in patterns:
        for m in pat.finditer(scan_text):
            if label == "lorem ipsum" and _is_lorem_prohibition_mention(
                text or "", m.start(), m.end()
            ):
                continue
            snippet = _snippet_at(text, m.start(), m.end())
            key = (label, snippet)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                PlaceholderHit(path=path, kind=kind, label=label, snippet=snippet)
            )
    return hits


def _format_hit_lines(hits: list[PlaceholderHit], *, budget: int) -> list[str]:
    lines: list[str] = []
    for hit in hits[:budget]:
        lines.append(f"`{hit.path}` · {hit.label} · 「{hit.snippet}」")
    more = len(hits) - len(lines)
    if more > 0:
        lines.append(f"…另有 {more} 处")
    return lines


def scan_placeholder_signals(
    artifact_contents: Mapping[str, str] | None,
    *,
    hard_exempt_paths: Iterable[str] | None = None,
) -> PlaceholderScanResult:
    """Scan landed file texts for hard / soft placeholder signals.

    Returns empty result when contents are missing or no content-surface file is
    present. Code files are skipped entirely (防误报).

    ``hard_exempt_paths`` — workspace-relative paths (or patterns) whose hard hits
    are downgraded (skipped for failures; soft warnings still collected). Exemption
    is declared on :class:`~agentcore.runtime.runs.types.Deliverable`, not inferred
    from filenames inside this module.
    """
    if not artifact_contents:
        return PlaceholderScanResult()

    exempt = tuple(hard_exempt_paths or ())
    hard_hits: list[PlaceholderHit] = []
    soft_hits: list[PlaceholderHit] = []
    for path, text in artifact_contents.items():
        if not path or text is None:
            continue
        if is_code_deliverable_path(path):
            continue
        if not is_content_deliverable_path(path):
            # Unknown / binary-ish extensions: skip (prefer pass over false fail).
            continue
        hard = _collect_hits(path, text, _HARD_PATTERNS, kind="hard")
        soft = _collect_hits(path, text, _SOFT_PATTERNS, kind="soft")
        if exempt and path_matches_placeholder_exempt(path, exempt):
            soft_hits.extend(soft)
        else:
            hard_hits.extend(hard)
            soft_hits.extend(soft)

    failures: list[str] = []
    warnings: list[str] = []
    if hard_hits:
        listed = _format_hit_lines(hard_hits, budget=_MAX_HITS_LISTED)
        detail = "；".join(listed)
        failures.append(
            f"交付正文含未替换占位符/硬信号（{len(hard_hits)} 处）：{detail}。"
            "请换成真实可上线内容后再交付，勿把 XXX / PLACEHOLDER / [占位] / lorem ipsum "
            "等占位稿原样写入正式产物。"
        )
    if soft_hits:
        listed = _format_hit_lines(soft_hits, budget=_MAX_HITS_LISTED)
        detail = "；".join(listed)
        # Soft only — delivery_status marks severity=warning; keep copy short (no
        # repeated「请核实后删除…」boilerplate on the acceptance card).
        warnings.append(
            f"含待核实/示例自注（{len(soft_hits)} 处）：{detail}。"
        )
    return PlaceholderScanResult(
        failures=failures,
        warnings=warnings,
        hits=hard_hits + soft_hits,
    )


def check_placeholder_failures(
    artifact_contents: Mapping[str, str] | None,
) -> list[str]:
    """Hard-signal failures only (empty when clean or not applicable)."""
    return scan_placeholder_signals(artifact_contents).failures


def check_placeholder_warnings(
    artifact_contents: Mapping[str, str] | None,
) -> list[str]:
    """Soft-signal warnings only (never fail the gate by themselves)."""
    return scan_placeholder_signals(artifact_contents).warnings
