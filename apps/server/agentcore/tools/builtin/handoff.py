"""handoff — a worker's structured 交接简报 + finish signal (完工交接简报单一源).

Worker-only, terminal. Semantics: 简报 = 【接力契约 + 增量交代】. A delegated worker calls
``handoff`` ONCE, in the SAME turn as its finished deliverable, to submit a STRUCTURED brief
(给主管 / 下游队员看): 结论 / 关键要点 / 关键假设 / 建议下一步；可选 ``motion_card``
（发现核心争议命题时建议开辩的唯一契约载体）。

Topology (prompt + this description say the same thing; engine gate unchanged):
- Nodes with downstream dependents **must** handoff — downstream relays on the brief
  (executor injects one correction shot; still missing → degraded synth).
- Leaf nodes (no dependents): call only when there is incremental briefing beyond the
  body (assumptions / risks / next steps / files list); a short self-evident deliverable
  may finish with a plain no-tool answer — no debrief, deliverable stands alone.

Why a tool, not a「## 交接简报」markdown section (its former form): the brief is structured DATA
for READERS (下游依赖注入 / CEO 综述 / run-detail 卡), so it travels in a structured channel and is
read straight off the call's arguments
(:func:`~agentcore.runtime.runs.serialize.debrief_from_transcript`),
never parsed back out of prose. The deliverable stays the worker's streamed ``content``; this tool
carries ONLY the brief and signals the run is done — so the run-detail「输出」(the deliverable) and
「交接简报」(this brief) can never overlap the way a retained-in-prose section did.

Terminal by design (``ToolEffect.HANDOFF``): the worker writes its deliverable as content and calls
``handoff`` in the same round to finish. A terminal effect KEEPS that round's content (only prose
before a NON-terminal tool is rolled back as narration, Fork-B) — so ``content`` == the deliverable
and the brief rides the tool args. ``final_text`` is empty: the deliverable is already the streamed
content, so nothing is appended to it.

Wired into the delegated worker toolset (``build_worker_registry``) and NOT into
``build_builtin_registry`` — so it never reaches the CEO's own toolset (``build_ceo_tool_registry``
derives the CEO subset from the builtins) or the read-only ``GET /tools`` capability catalog,
mirroring how ``escalate`` / ``post_note`` are wired in only where they belong.
"""

from __future__ import annotations

import contextlib
import re
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory, ToolEffect
from agentcore.runtime.runs.constants import HANDOFF_TOOL_NAME
from agentcore.tools.builtin.debate.schema import STANCE_MAX_CHARS
from agentcore.tools.builtin.motion_card import parse_motion_card
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)

# 建议开辩意图：收窄在「建议/推荐开辩」短语，避免误拦仅提及辩论事实的正文
# （如法律报告「一审辩论过程」）。只扫建议语境字段（summary / key_points / next_steps）。
_DEBATE_SUGGEST_RE = re.compile(
    r"(?:"
    r"建议(?:发起)?(?:一场)?(?:正反)?(?:对抗)?辩论"
    r"|建议开辩"
    r"|推荐(?:发起)?(?:一场)?(?:正反)?(?:对抗)?辩论"
    r"|推荐开辩"
    r"|宜(?:发起)?(?:一场)?(?:正反)?辩论"
    r"|宜开辩"
    r"|should\s+(?:open\s+a\s+)?debate"
    r"|recommend(?:s|ed)?\s+(?:a\s+)?debate"
    r")",
    re.IGNORECASE,
)

_MOTION_CARD_MISSING_TIP = (
    "交接内容已建议开辩/发起辩论，但未携带合规 `motion_card`。"
    "请把开辩建议写成 handoff 的结构化 `motion_card` 字段后重试"
    "（正文 markdown 表、key_points 散文【不能】代替）。"
    "最小示例："
    '{"motion":"争议命题","sides":[{"key":"pro","name":"正方","stance":"支持该主张"},'
    '{"key":"con","name":"反方","stance":"反对该主张"}],'
    '"fact_pointers":[],"rationale":"继续调研无法消解对立，须对抗交锋"}。'
)


def _body_chars(context: ToolContext) -> int:
    """Deliverable prose length for this round (0 when unset / unknown)."""
    n = context.round_content_chars
    return int(n) if isinstance(n, int) and n >= 0 else 0


def _suggestion_context(arguments: dict[str, Any]) -> str:
    """拼接建议语境字段（不含交付正文 / assumptions 事实叙述）。"""
    parts: list[str] = [str(arguments.get("summary") or "")]
    key_points = arguments.get("key_points")
    if isinstance(key_points, list):
        parts.extend(str(p) for p in key_points)
    elif key_points is not None:
        parts.append(str(key_points))
    parts.append(str(arguments.get("next_steps") or ""))
    return "\n".join(parts)


def claims_debate_suggestion(arguments: dict[str, Any]) -> bool:
    """建议语境字段是否声称「建议/推荐开辩」。

    仅扫 summary / key_points / next_steps；提及辩论事实（如「一审辩论过程」）不触发。
    """
    return bool(_DEBATE_SUGGEST_RE.search(_suggestion_context(arguments)))


class HandoffTool:
    """The worker's structured 交接简报 + finish primitive (terminal).

    Stateless: the call returns a terminal ``ToolResult`` that ends the run; the brief itself is
    read off THIS call's arguments by the executor's transcript harvest, so the tool owns only the
    done-signal + a short ack (the executor owns event shape / RunState, 引擎纯化).
    """

    registration = ToolRegistration(
        surface=ToolSurface.WORKER_ONLY,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=HANDOFF_TOOL_NAME,
            description=(
                "提交交接简报并收尾。简报 =【接力契约 + 增量交代】（给主管 / 下游队员看的结构化"
                "交接，不是正文复述）。\n"
                "· 有下游队员依赖你的产出时：完成后【必须】调用——下游靠简报接力。\n"
                "· 无下游（叶节点）时：仅当正文之外有值得交代的增量（关键假设 / 风险 / "
                "建议下一步 / "
                "落盘文件清单）才调用；简短自明的交付写完正文直接结束即可，不必为交而交。\n"
                "用法：先把【交付正文】写完（或用 file_write 落盘），再在【同一轮】调用；调用即代表"
                "本次任务【已完成】，之后不再继续。\n"
                "简报只需几句、精炼具体：summary 一句话核心结论（必填）；key_points 下游 / 主管"
                "最该知道的 2-4 条（具体数字 / 文件路径 / 关键决定，别空泛）；assumptions 信息不足"
                "时你采用的关键假设（没有就省略）；next_steps 顺带给主管的后续建议（没有就省略——"
                "它与 escalate 不同：escalate 是『缺了它整件事会走偏、需现在有人拍板』，这里是"
                "『我已做完、提示个后续方向』）。\n"
                "· motion_card（可选对象字段）：仅当发现【必须对抗交锋】的核心争议、要建议开辩时"
                "【必须】填本参数——这是主管呈报 / 系统开辩芯片的【唯一】结构化载体。"
                "正文 markdown 表、key_points 散文写『命题卡已就位』【一律不算】；无本字段 ="
                "无建议开辩。字段要短：sides[].stance 一句薄立场；fact_pointers / rationale 必填"
                "（指针可 []）；勿把长文塞进卡里以免 JSON 写坏。\n"
                "别把简报重复写进交付正文，也不要在还没产出交付时就调用它。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "结论：一句话说清你这次做出了什么 / 核心结论。",
                    },
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "关键要点：下游或主管最该知道的 2-4 条（具体数字 / 文件路径 / "
                            "关键决定，别空泛）。"
                        ),
                    },
                    "assumptions": {
                        "type": "string",
                        "description": "关键假设：信息不足时你采用的关键假设（没有就省略此条）。",
                    },
                    "next_steps": {
                        "type": "string",
                        "description": (
                            "建议下一步：基于你这一环的发现，团队 / 用户接下来值得考虑做什么"
                            "（没有就省略此条）。"
                        ),
                    },
                    "motion_card": {
                        "type": "object",
                        "description": (
                            "建议开辩时【必填】的结构化命题卡对象（不是字符串、不是正文表格）。"
                            "仅当核心争议必须对抗交锋、而非继续调研时填写；省略 = 不建议开辩、"
                            "交接其它字段不受影响。sides[].stance 薄立场"
                            f"（一句话立场倾向；硬上限 {STANCE_MAX_CHARS} 字作兜底）："
                            "只写结论倾向，禁换行/分号/论证展开与论点清单。"
                            "散文提及命题【不能】代替本对象。"
                        ),
                        "properties": {
                            "motion": {
                                "type": "string",
                                "description": "争议命题（可直接作 debate 的 motion）。",
                            },
                            "sides": {
                                "type": "array",
                                "description": (
                                    "参与方（≥2）：每方 key / name / stance；"
                                    f"stance 一句话立场倾向（硬上限 {STANCE_MAX_CHARS} 字作兜底）。"
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "key": {
                                            "type": "string",
                                            "description": "机器标识（唯一英文短词）。",
                                        },
                                        "name": {
                                            "type": "string",
                                            "description": "展示名（立场 / 视角名）。",
                                        },
                                        "stance": {
                                            "type": "string",
                                            "maxLength": STANCE_MAX_CHARS,
                                            "description": (
                                                f"一句话结论倾向（硬上限 {STANCE_MAX_CHARS} 字"
                                                "作兜底）；禁换行/分号/论证展开与论点清单。"
                                            ),
                                        },
                                    },
                                    "required": ["key", "name", "stance"],
                                },
                            },
                            "fact_pointers": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "支撑事实指针（#rN 台账 / 文件路径 / URL）；只指事实不装论点。"
                                ),
                            },
                            "rationale": {
                                "type": "string",
                                "description": (
                                    "为何必须对抗交锋而非继续调研（防见分歧就建议开辩）。"
                                ),
                            },
                            "form": {
                                "type": "string",
                                "enum": ["debate", "red_team", "roundtable"],
                                "description": "辩论形态；默认 debate。",
                            },
                        },
                        "required": ["motion", "sides", "fact_pointers", "rationale"],
                    },
                },
                "required": ["summary"],
            },
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        from agentcore.runtime.engine.tool_protocol_sanitize import (
            sanitize_protocol_text,
            sanitize_tool_args,
        )

        # Defense in depth: strip vendor protocol tags from brief fields (tool_exec
        # already cleans before invoke; harvest path may still see raw transcript).
        cleaned = sanitize_tool_args(arguments) if isinstance(arguments, dict) else arguments
        if isinstance(cleaned, dict):
            arguments = cleaned
            # key_points: tolerate markdown bullet string / JSON-array-as-string via the
            # shared coerce path (ask_user.schema); truly bad JSON still fails at parse.
            if "key_points" in arguments:
                from agentcore.tools.builtin.ask_user.schema import (
                    ListArgError,
                    coerce_list_arg,
                )

                with contextlib.suppress(ListArgError):
                    arguments["key_points"] = [
                        str(p).strip()
                        for p in coerce_list_arg(
                            arguments.get("key_points"),
                            field="key_points",
                            allow_markdown_bullets=True,
                        )
                        if str(p).strip()
                    ]
        summary = sanitize_protocol_text(str(arguments.get("summary") or "")).strip()
        card, card_err = parse_motion_card(arguments.get("motion_card"))
        if card_err:
            logger.info(
                "worker.handoff",
                run_id=context.run_id,
                has_summary=bool(summary),
                chars=len(summary),
                body_chars=_body_chars(context),
                has_motion_card=False,
                rejected="motion_card",
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=card_err,
            )
        # 建议开辩却无合规卡 → 拒收（success=False 不触发交接），与卡字段校验错误可区分。
        if card is None and claims_debate_suggestion(arguments):
            logger.info(
                "worker.handoff",
                run_id=context.run_id,
                has_summary=bool(summary),
                chars=len(summary),
                body_chars=_body_chars(context),
                has_motion_card=False,
                rejected="debate_suggest_without_motion_card",
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=_MOTION_CARD_MISSING_TIP,
            )
        # 成篇质量：有下游时禁止空交（地板 = 合同 min_length，0 则仅要求非空）。
        # 豁免认 landed_artifact_kinds 中的 prose（跨 replace 存活）；骨架/空落盘不算。
        # 勿依赖 has_landed_files bool——经 dataclasses.replace 会丢。
        if context.handoff_requires_body:
            from agentcore.runtime.runs.research_quality import (
                upstream_body_floor_satisfied,
            )

            body_chars = _body_chars(context)
            floor = max(0, int(context.handoff_min_body_chars or 0))
            if not upstream_body_floor_satisfied(
                body_chars=body_chars,
                landed_artifact_kinds=context.landed_artifact_kinds,
                min_body_chars=floor,
            ):
                kinds = context.landed_artifact_kinds or {}
                only_skeleton = bool(kinds) and all(v == "skeleton" for v in kinds.values())
                floor_hint = (
                    f"至少 {floor} 字（合同 min_length）"
                    if floor > 0
                    else "非空正文"
                )
                land_hint = (
                    "已落盘的是骨架/提纲（skeleton），不算成篇交付；请补写实质正文并 "
                    f"file_write/file_append 成 prose，或在本轮写出{floor_hint}后再 handoff。"
                    if only_skeleton
                    else (
                        f"本轮正文仅 {body_chars} 字（须{floor_hint}，"
                        "或先落盘成篇 prose 产物后再交；骨架/空文件不算）。"
                        "请先写完交付正文并落盘，或在本轮写出足够正文后再调用 handoff——"
                        "禁止空壳简报进入下游任务。"
                    )
                )
                logger.info(
                    "worker.handoff",
                    run_id=context.run_id,
                    has_summary=bool(summary),
                    chars=len(summary),
                    body_chars=body_chars,
                    has_motion_card=card is not None,
                    rejected="empty_body",
                    only_skeleton=only_skeleton,
                    min_body_chars=floor,
                )
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=f"空交付不得交接：有下游队员依赖你的产出，但{land_hint}",
                    contract_failure=True,
                )
        logger.info(
            "worker.handoff",
            run_id=context.run_id,
            has_summary=bool(summary),
            chars=len(summary),
            body_chars=_body_chars(context),
            has_motion_card=card is not None,
        )
        # Terminal (HANDOFF): the deliverable is already the run's streamed content, so this
        # carries NO final_text (nothing to append). The structured brief is read off THIS call's
        # arguments by serialize.debrief_from_transcript — the tool only signals「done + brief
        # submitted」. Its output is never fed back to the model (the loop ends here); it lands in
        # the transcript as a plain tool result for a later 续写 replay.
        return ToolResult(
            tool_call_id="",
            success=True,
            output="已收尾并提交交接简报。",
            effect=ToolEffect.HANDOFF,
            final_text="",
        )
