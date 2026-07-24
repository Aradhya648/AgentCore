"""Sparse workspace file listing for CEO overview + worker manifests.

Default injection is relevance-first (双模式工作区 · 清单稀疏化):

- **本回合附件** — paths under ``attachments/``
- **本对话 scratch** — for 裸聊 the whole workspace *is* the scratch, so non-
  attachment files list normally (capped); project chats have no per-conv
  scratch under the shared folder, so scratch entries are empty here
- **同回合队友产出** — layered by the worker manifest (role-attributed); not
  handled in this module
- **项目共享其余文件** — never enumerated; one summary line with the count

Project mode optionally surfaces a few newest non-attachment paths as
「最近触达」so the model still sees recent activity without dumping the tree.
"""

from __future__ import annotations

from agentcore.workspace.attachments import ATTACHMENTS_DIR

# Newest non-attachment paths kept as an explicit supplement in project mode
# (beyond attachments). The rest collapse into the summary line.
PROJECT_RECENT_SUPPLEMENT = 5


def is_attachment_path(path: str) -> bool:
    """Whether ``path`` lives under the resident ``attachments/`` directory."""
    p = path.replace("\\", "/").lstrip("./")
    return p == ATTACHMENTS_DIR or p.startswith(f"{ATTACHMENTS_DIR}/")


def partition_sparse_paths(
    index_paths: list[str],
    *,
    shared_workspace: bool,
) -> tuple[list[tuple[str, str]], int]:
    """Split an index into (labeled rows to list, remaining shared count).

    ``index_paths`` should already be newest-first when order matters (project
    supplement). Each row is ``(path, label)``:

    - attachments → 「附件」
    - bare-chat scratch / project recent supplement → 「工作区已有」/「最近触达」
    - ``remaining`` is the count of shared project files *not* listed (0 for 裸聊)
    """
    attachments: list[str] = []
    others: list[str] = []
    for path in index_paths:
        if is_attachment_path(path):
            attachments.append(path)
        else:
            others.append(path)

    rows: list[tuple[str, str]] = [(p, "附件") for p in attachments]

    if not shared_workspace:
        rows.extend((p, "工作区已有") for p in others)
        return rows, 0

    # Project shared space: keep a few recent non-attachments, summarize the rest.
    keep = others[:PROJECT_RECENT_SUPPLEMENT]
    rows.extend((p, "最近触达") for p in keep)
    remaining = max(0, len(others) - len(keep))
    return rows, remaining


def format_remaining_summary(remaining: int) -> str:
    """One-line elision for shared project files not listed individually."""
    return f"另有 {remaining} 个文件，需要时用 file_list / grep"
