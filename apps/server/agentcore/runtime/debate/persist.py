"""辩论双产物落盘 —— 收口时机制性写入案子工作区 ``AgentCore/文档/debate/``。

与 journal / UI 同源：决策简报与交锋叙事线 L1 用 :mod:`types` 的同一套渲染。
落盘失败只记警告，不阻断收口主流程；成功路径供 CEO 输出尾部引用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agentcore.core.logging import get_logger
from agentcore.runtime.debate.types import (
    DebateResult,
    _form_label,
    _render_brief,
    _render_narrative_l1,
    _stop_label,
)
from agentcore.workspace.protocol import WorkspaceBackend
from agentcore.workspace.stage_dirs import DEBATE_DIR

logger = get_logger(__name__)
_BRIEF_NAME = "决策简报"
_NARRATIVE_NAME = "交锋叙事线"
# 文件名非法字符（含路径分隔与 Windows 保留符）；空白压掉以保持短可读。
_UNSAFE = re.compile(r'[\0-\x1f\\/:*?"<>|]+')
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class DebateArtifactPaths:
    """工作区相对路径（POSIX）：简报 + 叙事线各一份。"""

    brief: str
    narrative: str

    def as_list(self) -> list[str]:
        return [self.brief, self.narrative]


def artifact_stamp(moderator_run_id: str) -> str:
    """从主持人 run_id（``debate_<uuid>``）取短 token，多场辩论互不覆盖。"""
    raw = (moderator_run_id or "").removeprefix("debate_").replace("-", "")
    return (raw[:8] if raw else "") or "场次"


def artifact_paths(*, motion: str, stamp: str) -> DebateArtifactPaths:
    """命名：``AgentCore/文档/debate/{产物名}·{辩题短语}·{场次}.md``。"""
    slug = _motion_slug(motion)
    token = (stamp or "").strip() or "场次"
    stem = f"{slug}·{token}"
    return DebateArtifactPaths(
        brief=f"{DEBATE_DIR}/{_BRIEF_NAME}·{stem}.md",
        narrative=f"{DEBATE_DIR}/{_NARRATIVE_NAME}·{stem}.md",
    )


def render_brief_file(
    result: DebateResult, *, act1_summary_path: str | None = None
) -> str:
    """决策简报完整 markdown（含命题元信息 + 与 CEO/UI 同源正文）。"""
    return _compose_file(
        title=_BRIEF_NAME,
        result=result,
        section=_render_brief(result.brief, result.config),
        act1_summary_path=act1_summary_path,
    )


def render_narrative_file(
    result: DebateResult, *, act1_summary_path: str | None = None
) -> str:
    """交锋叙事线完整 markdown（L1 焦点小结流，与 CEO 输出同源）。"""
    return _compose_file(
        title=_NARRATIVE_NAME,
        result=result,
        section=_render_narrative_l1(result.rounds),
        act1_summary_path=act1_summary_path,
    )


def format_artifact_footer(paths: DebateArtifactPaths) -> str:
    """附在 ``to_ceo_output`` 尾部，供 CEO 呈报时引用落盘路径。"""
    return f"\n\n【工作区落盘】`{paths.brief}`；`{paths.narrative}`"


async def persist_debate_artifacts(
    backend: WorkspaceBackend,
    result: DebateResult,
    *,
    stamp: str,
) -> DebateArtifactPaths | None:
    """将双产物写入工作区；失败返回 ``None``（不抛），成功返回相对路径。

    原子语义：要么 brief+narrative 都在，要么都不在——第二份失败时清理已写的第一份，
    避免半套文件残留（失败降级不阻断收口的既有语义保持）。

    有幕 1 汇总文件时，双产物文件头机制性引用其路径；无则省略（零行为）。
    """
    from agentcore.runtime.debate.research_dossier import (
        SYNTHESIZER_FILE,
        workspace_has_synthesizer,
    )

    act1_path: str | None = None
    try:
        if await workspace_has_synthesizer(backend):
            act1_path = SYNTHESIZER_FILE
    except Exception:  # noqa: BLE001 — 互链探测失败不阻断落盘
        act1_path = None

    paths = artifact_paths(motion=result.config.motion, stamp=stamp)
    brief_written = False
    try:
        await backend.write(
            paths.brief, render_brief_file(result, act1_summary_path=act1_path)
        )
        brief_written = True
        await backend.write(
            paths.narrative,
            render_narrative_file(result, act1_summary_path=act1_path),
        )
    except Exception as exc:  # noqa: BLE001 — 落盘不得阻断收口
        if brief_written:
            try:
                await backend.delete(paths.brief, permanent=True)
            except Exception as cleanup_exc:  # noqa: BLE001 — 尽力清理
                logger.warning(
                    "debate.artifacts_cleanup_failed",
                    path=paths.brief,
                    error=str(cleanup_exc),
                )
        logger.warning(
            "debate.artifacts_persist_failed",
            motion=result.config.motion[:80],
            brief=paths.brief,
            narrative=paths.narrative,
            error=str(exc),
        )
        return None
    logger.info(
        "debate.artifacts_persisted",
        brief=paths.brief,
        narrative=paths.narrative,
    )
    return paths


def _motion_slug(motion: str, *, max_len: int = 24) -> str:
    text = _UNSAFE.sub("", (motion or "").strip())
    text = _WS.sub("", text)
    return text[:max_len] or "辩题"


def _compose_file(
    *,
    title: str,
    result: DebateResult,
    section: str,
    act1_summary_path: str | None = None,
) -> str:
    meta = (
        f"- **命题**：{result.config.motion}\n"
        f"- **形态**：{_form_label(result.config.form)}\n"
        f"- **收场**：{_stop_label(result.stop_reason)} · {len(result.rounds)} 轮\n"
    )
    if act1_summary_path:
        meta += f"- **幕1 汇总**：`{act1_summary_path}`\n"
    body = section
    if body.startswith("###"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
    body = body.strip()
    parts = [f"# {title}", "", meta.rstrip(), ""]
    if body:
        parts.append(body)
        parts.append("")
    return "\n".join(parts)
