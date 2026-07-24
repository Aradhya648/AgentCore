"""Regenerate the event catalog section in 对话日志分析指南.md from the registry.

Run after ``sync_log_event_registry.py`` (or anytime the catalog changes)::

    uv run python scripts/gen_log_event_docs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ -> apps/server
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentcore.observability.events import get_registry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "05-平台与运维" / "对话日志分析指南.md"
BEGIN = "<!-- BEGIN AUTO:log-event-catalog -->"
END = "<!-- END AUTO:log-event-catalog -->"


def render_table() -> str:
    """Docs carry only the enriched (description/fields) subset.

    The full name list is code-visible in ``catalog.py`` — repeating all ~500
    rows here is what doc-governance calls out as noise (文档只写代码看不出来的).
    """
    specs = get_registry().all_specs()
    enriched = [s for s in specs if s.description or s.fields]
    lines = [
        BEGIN,
        "",
        f"> 全量 **{len(specs)}** 个在用事件登记于 "
        "`apps/server/agentcore/observability/catalog.py`（权威源，勿手改）；"
        f"下表只列 **{len(enriched)}** 个带说明/字段富化的重点事件。更新：",
        "> `cd apps/server && uv run python scripts/sync_log_event_registry.py"
        " && uv run python scripts/gen_log_event_docs.py`",
        "",
        "| 事件 | 说明 | 关键字段 |",
        "|---|---|---|",
    ]
    for spec in enriched:
        desc = spec.description or "—"
        if spec.fields:
            fields = ", ".join(f"`{k}`:{v}" for k, v in sorted(spec.fields.items()))
        else:
            fields = "—"
        lines.append(f"| `{spec.name}` | {desc} | {fields} |")
    lines.extend(["", END])
    return "\n".join(lines) + "\n"


def upsert_section(doc_text: str, section: str) -> str:
    if BEGIN in doc_text and END in doc_text:
        pre = doc_text.split(BEGIN, 1)[0]
        post = doc_text.split(END, 1)[1]
        # drop leading newline after END marker block
        if post.startswith("\n"):
            post = post[1:]
        return pre + section + post
    # Append under a standard heading.
    anchor = "\n## 事件注册表\n"
    block = "\n## 事件注册表\n\n" + section
    if anchor in doc_text:
        # replace existing heading body until next ##
        idx = doc_text.index(anchor)
        rest = doc_text[idx + len(anchor) :]
        next_h = rest.find("\n## ")
        if next_h >= 0:
            return doc_text[:idx] + block + rest[next_h:]
        return doc_text[:idx] + block
    return doc_text.rstrip() + "\n" + block


def main() -> None:
    if not DOC.exists():
        raise SystemExit(f"doc not found: {DOC}")
    section = render_table()
    updated = upsert_section(DOC.read_text(encoding="utf-8"), section)
    # Atomic replace avoids Windows Errno 22 when the doc is briefly locked.
    tmp = DOC.with_suffix(DOC.suffix + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    tmp.replace(DOC)
    print(f"updated {DOC} ({len(get_registry().names())} events)")


if __name__ == "__main__":
    main()
