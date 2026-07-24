"""SECTION marker inject + turn-ceiling light shell checks (build_website Wave3 A/B3).

Hard write contract: replace the whole body between
``<!-- SECTION:sN START -->`` … ``<!-- SECTION:sN END -->`` without needing an
exact ``str_replace`` match of the prior placeholder (indent / whitespace safe).

Light acceptance (B3): when whole-page QA is skipped under the turn token
ceiling, still flag missing critical site files and residual ``{{…}}`` slots.
"""

from __future__ import annotations

import re
from typing import Any

# Match playbook skeleton artifacts (build_website / build_toolshed).
CRITICAL_SITE_PATHS: tuple[str, ...] = (
    "site/index.html",
    "site/styles.css",
    "site/main.js",
)

REASON_WEBSITE_SHELL = "website_shell_incomplete"

_MUSTACHE_RE = re.compile(r"\{\{[^{}\n]+\}\}")
_HTML_SUFFIXES = (".html", ".htm")
_SECTION_ID_RE = re.compile(r"^s?\d+$", re.IGNORECASE)


class SectionMarkerError(ValueError):
    """SECTION START/END pair missing, mismatched, or ambiguous."""


def normalize_section_id(section: str) -> str:
    """Normalize ``s0`` / ``S0`` / ``0`` → ``s0``."""
    raw = (section or "").strip()
    if not raw:
        raise SectionMarkerError("section 不能为空（如 s0）")
    if not _SECTION_ID_RE.match(raw):
        raise SectionMarkerError(
            f"section 格式无效：{section!r}（须为 sN，如 s0 / s1）"
        )
    if raw[0] in "sS":
        return f"s{int(raw[1:])}"
    return f"s{int(raw)}"


def section_start_marker(section_id: str) -> str:
    slug = normalize_section_id(section_id)
    return f"<!-- SECTION:{slug} START -->"


def section_end_marker(section_id: str) -> str:
    slug = normalize_section_id(section_id)
    return f"<!-- SECTION:{slug} END -->"


def _section_pair_re(slug: str) -> re.Pattern[str]:
    # Whitespace-tolerant markers; body is anything (DOTALL) between the pair.
    return re.compile(
        rf"(<!--\s*SECTION:{re.escape(slug)}\s+START\s*-->)"
        rf"(.*?)"
        rf"(<!--\s*SECTION:{re.escape(slug)}\s+END\s*-->)",
        re.DOTALL | re.IGNORECASE,
    )


def inject_section_html(html: str, section: str, body: str) -> str:
    """Replace the interior of one SECTION marker pair; keep the markers.

    ``body`` is inserted as-is between START and END (leading/trailing newlines
    normalized to a single newline on each side for readable HTML).
    """
    slug = normalize_section_id(section)
    pattern = _section_pair_re(slug)
    matches = list(pattern.finditer(html))
    if not matches:
        raise SectionMarkerError(
            f"在目标文件中找不到 SECTION 标记对 "
            f"`<!-- SECTION:{slug} START -->`…`<!-- SECTION:{slug} END -->`"
        )
    if len(matches) > 1:
        raise SectionMarkerError(
            f"SECTION:{slug} 标记对不唯一（匹配 {len(matches)} 处）；"
            "请先修骨架使每个分区只有一对 START/END"
        )
    m = matches[0]
    inner = body if body.endswith("\n") or body == "" else body + "\n"
    if inner and not inner.startswith("\n"):
        inner = "\n" + inner
    return html[: m.start()] + m.group(1) + inner + m.group(3) + html[m.end() :]


def light_website_acceptance_gaps(
    *,
    present_paths: set[str] | frozenset[str],
    html_texts: dict[str, str],
    critical_paths: tuple[str, ...] = CRITICAL_SITE_PATHS,
) -> list[dict[str, str]]:
    """Mechanical shell gaps: missing critical files + residual mustache in HTML.

    Pure function for tests; callers load workspace texts then invoke.
    """
    gaps: list[dict[str, str]] = []
    missing = [p for p in critical_paths if p not in present_paths]
    if missing:
        gaps.append(
            {
                "description": "关键站点文件缺失：" + "、".join(missing),
                "reason": REASON_WEBSITE_SHELL,
            }
        )
    mustache_paths: list[str] = []
    for path, text in sorted(html_texts.items()):
        if not path.lower().endswith(_HTML_SUFFIXES):
            continue
        if _MUSTACHE_RE.search(text or ""):
            mustache_paths.append(path)
    if mustache_paths:
        gaps.append(
            {
                "description": (
                    "站点 HTML 仍有未替换模板槽 {{…}}："
                    + "、".join(mustache_paths)
                ),
                "reason": REASON_WEBSITE_SHELL,
            }
        )
    return gaps


async def collect_light_website_acceptance_gaps(backend: Any) -> list[dict[str, str]]:
    """Read workspace and return B3 light-acceptance gaps (best-effort)."""
    from agentcore.workspace.protocol import PathNotFound, WorkspaceError

    present: set[str] = set()
    html_texts: dict[str, str] = {}

    async def _try_read(path: str) -> str | None:
        try:
            return await backend.read(path)
        except PathNotFound:
            return None
        except WorkspaceError:
            return None

    for path in CRITICAL_SITE_PATHS:
        text = await _try_read(path)
        if text is None:
            continue
        present.add(path)
        if path.lower().endswith(_HTML_SUFFIXES):
            html_texts[path] = text

    # Extra HTML under site/ (section fragments, etc.) — empty shell often lives here
    # when assemble was skipped.
    try:
        entries, _truncated = await backend.index_files(cap=200, order="path")
    except Exception:  # noqa: BLE001 — light check must not break skip materialise
        entries = []
    for path in entries:
        if not isinstance(path, str):
            continue
        norm = path.replace("\\", "/").lstrip("./")
        if not norm.startswith("site/"):
            continue
        if not norm.lower().endswith(_HTML_SUFFIXES):
            continue
        if norm in html_texts:
            continue
        text = await _try_read(norm)
        if text is None:
            continue
        present.add(norm)
        html_texts[norm] = text

    return light_website_acceptance_gaps(
        present_paths=present,
        html_texts=html_texts,
    )
