"""Parallel tool execution for one ReAct round."""

import asyncio
import contextlib
import json
import time
from dataclasses import replace
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolEffect
from agentcore.llm.provider.protocol import LLMMessage, ToolCall
from agentcore.runtime.approvals import ApprovalDecision, ApprovalGate, tool_call_requires_approval
from agentcore.runtime.citations import (
    annotate_ledger_ids,
    annotate_tool_citations,
    merge_citations,
    normalize_citation_url,
)
from agentcore.runtime.events import (
    EventSink,
    run_phase,
    tool_use_end,
    tool_use_progress,
    tool_use_start,
)
from agentcore.runtime.evidence_ledger import EvidenceLedgerCore
from agentcore.runtime.facts import ToolCallFact, record_turn_fact
from agentcore.runtime.ledger_channel import emit_ledger_delta
from agentcore.runtime.loop_controller import (
    ERROR_CLASS_PERMANENT,
    ERROR_CLASS_PERMISSION,
    ERROR_CLASS_VALIDATION,
    ToolAttempt,
    classify_segmented_write_reject,
    fingerprint_tool_call,
)
from agentcore.runtime.tool_deadline import reset_tool_deadline, set_tool_deadline
from agentcore.tools.protocol import ToolContext, ToolResult
from agentcore.tools.registry import ToolRegistry

from .constants import MAX_PARALLEL_TOOLS
from .timeout import resolve_tool_timeout
from .tool_protocol_sanitize import (
    salvage_handoff_raw_arguments,
    sanitize_raw_tool_arguments,
    sanitize_tool_args,
    sanitize_tool_name,
    unwrap_nested_delegate_arguments,
)

logger = get_logger(__name__)

# Marker in tool_use_start.arguments when JSON parse failed — must not look like a
# successfully parsed empty object ``{}`` (journal / UI 假象).
_ARGS_PARSE_FAILED_MARKER: dict[str, Any] = {"__args_parse_failed__": True}

# Write/landing tools: parse failures are usually「整篇正文塞进 tool JSON」— steer to
# segmented writing, never disable the pen, never teach the user to escape quotes.
_WRITE_PARSE_TOOLS = frozenset(
    {"file_write", "file_append", "str_replace", "write_section", "file_move"}
)

# User-visible process-line copy for write-tool args parse failures (人话).
_USER_WRITE_PARSE_MSG = "长文保存失败，改成分段写入继续。"

# 工具失败机器尾注 (files_touched 成功口径 · 消费方见 runtime/runs/serialize.py):
# LLMMessage 无独立 success 字段；失败/拒绝路径在 tool content 末追加此 marker，让
# files_touched_from_transcript 按 tool_call_id 关联后只记账「无失败尾注」的 file 工具结果。
# 与 code_execute 的 ``<!--agentcore:written_files:…-->`` 同构：producer 在此、consumer 在
# serialize，格式靠 round-trip 单测锁死。禁止用拒绝文案子串匹配。
TOOL_FAILED_MARKER = "<!--agentcore:tool_failed-->"

# 写盘类工具名（与 serialize._FILE_PRODUCT_ARG 对齐）：miss / allowlist 分流用。
_FILE_PRODUCT_TOOL_NAMES = frozenset(
    {"file_write", "file_append", "str_replace", "file_move"}
)


def _attempt_meta_with_landing_path(
    name: str,
    args: Any,
    base: dict[str, Any] | None = None,
    *,
    error: str = "",
    contract_failure: bool = False,
) -> dict[str, Any]:
    """Forward landing-tool path (+ write-reject class) into ``ToolAttempt.meta``."""
    from agentcore.runtime.runs.landing_product import landing_tool_path_from_args

    meta: dict[str, Any] = dict(base or {})
    path = landing_tool_path_from_args(name, args if isinstance(args, dict) else None)
    if path:
        meta["path"] = path
    reject_class = classify_segmented_write_reject(
        name, error=error, contract_failure=contract_failure
    )
    if reject_class:
        meta["segmented_write_reject"] = reject_class
    # Permanent liveness: ensure first-fail retire of this tool (loop_controller).
    if meta.get("liveness_timeout") and "retire_tools" not in meta and name:
        meta["error_class"] = ERROR_CLASS_PERMANENT
        meta["retire_tools"] = [name]
        if not meta.get("retire_message"):
            meta["retire_message"] = (
                f"工具 `{name}` 因活性挂起已停用——请换路径推进，禁止原样重试。"
            )
    return meta

# Aggregable tip length for ``tool.execute_end`` reason (status=error).
_TOOL_ERROR_REASON_MAX = 200


def _file_read_round_coalesce_key(args: dict[str, Any]) -> str | None:
    """Same-round parallel ``file_read`` coalesce key: normalized path only.

    Offset/limit variants still share one underlying read (fan-out); only full
    reads bump ``file_read_counts``. Empty path → no coalesce.
    """
    if not isinstance(args, dict):
        return None
    path = str(args.get("path") or "").strip().replace("\\", "/")
    return path or None


def _clone_tool_result(result: ToolResult, tool_call_id: str) -> ToolResult:
    """Fan-out copy of a shared ``file_read`` result for a sibling tool_call."""
    return replace(
        result,
        tool_call_id=tool_call_id,
        citations=list(result.citations) if result.citations else None,
        metadata=dict(result.metadata) if result.metadata else {},
        display=dict(result.display) if result.display else None,
    )


def _short_tool_error_reason(text: str, *, limit: int = _TOOL_ERROR_REASON_MAX) -> str:
    """Collapse whitespace and truncate for log aggregation (not the full transcript)."""
    collapsed = " ".join((text or "").split())
    if not collapsed:
        return "Unknown error"
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)].rstrip() + "…"


def with_tool_failed_marker(content: str) -> str:
    """Append the machine failure trailer (idempotent)."""
    body = (content or "").rstrip()
    if TOOL_FAILED_MARKER in body:
        return body
    return f"{body}\n{TOOL_FAILED_MARKER}" if body else TOOL_FAILED_MARKER


def _failed_tool_message(tool_call_id: str, content: str) -> LLMMessage:
    return LLMMessage(
        role="tool", content=with_tool_failed_marker(content), tool_call_id=tool_call_id
    )


def _missing_tool_feedback(
    missing: str,
    *,
    raw_name: str | None,
    registry: ToolRegistry,
) -> tuple[str, str, bool]:
    """Build user-facing text + log status + policy flag for a registry miss.

    Known declared tools that are absent from *this* registry are usually audience
    or assembly gates (CEO vs worker, cloud execution withheld) — not typos. Those
    get an actionable message and ``policy_failure`` so the run circuit breaker
    does not burn on repeated role mistakes.
    """
    from agentcore.tools.registration import (
        declared_tool_names,
        execution_class_tool_names,
        worker_only_tool_names,
    )

    worker_only = worker_only_tool_names()
    execution = execution_class_tool_names()
    declared = declared_tool_names()

    if missing in worker_only and missing in execution:
        return (
            (
                f"工具 '{missing}' 当前工具面不可用。"
                "若你是 CEO：写盘/跑代码/跑测试须 `delegate` 派给 worker，勿亲自调用。"
                "若你是 worker：本回合未装配执行类工具（见 `<workspace_context>` 的"
                "「本回合执行能力」），勿空转重试。"
            ),
            "not_assembled",
            True,
        )
    if missing in worker_only:
        return (
            (
                f"工具 '{missing}' 仅供委派 worker 使用，当前工具面不可用。"
                "请用 delegate 派工执行，勿亲自调用该工具。"
            ),
            "audience_deny",
            True,
        )
    if missing in declared:
        return (
            (
                f"工具 '{missing}' 本回合未装配到当前工具面（环境或角色门控）。"
                "请改用已提供的工具，勿空转重试同一名称。"
            ),
            "not_assembled",
            True,
        )

    from agentcore.runtime.resolve.ceo_surface import COORDINATION_GATED_TOOLS

    # 协调闸内工具（至少 wait）：未装配时勿 fuzzy 成 git 等无关工具。
    if missing in COORDINATION_GATED_TOOLS:
        if missing == "wait":
            return (
                (
                    f"工具 '{missing}' 当前未装配到工具面。"
                    "若团队协调已启动：请空响应等待下一批事件，勿改调其他工具占位。"
                ),
                "not_found",
                False,
            )
        return (
            (
                f"工具 '{missing}' 当前未装配到工具面（仅协调期提供）。"
                "请改用已提供的工具，或空响应等待；勿猜测相近工具名。"
            ),
            "not_found",
            False,
        )

    suggestions = registry.suggest_names(missing)
    did_you_mean = f"你是否想用：{' / '.join(suggestions)}？" if suggestions else ""
    if raw_name and raw_name != missing:
        error_msg = (
            f"Tool '{missing}' not found"
            f"（已剥离协议标签残留：{raw_name!r} → {missing!r}）。"
            f"{did_you_mean}"
            "请使用合法工具名（如 web_search）原样重试，勿夹带 XML/协议标签。"
        )
    else:
        error_msg = (
            f"Tool '{missing}' not found。"
            f"{did_you_mean}"
            "请使用合法工具名原样重试，勿夹带协议标签。"
        )
    return error_msg, "not_found", False


def _format_args_parse_error(
    tool_name: str, raw: str, exc: json.JSONDecodeError
) -> tuple[str, str]:
    """Return ``(model_facing, user_facing)`` for illegal tool-call arguments JSON.

    Write/landing tools get a segmented-write steer for the model and a short human
    line for the process timeline — never「请修复转义后原样重发」exposed to users.
    Other tools keep the technical tip for both surfaces.
    """
    pos = exc.pos if isinstance(exc.pos, int) else 0
    # Window around the failure so the model can spot unescaped quotes without a full dump.
    left = max(0, pos - 24)
    right = min(len(raw), pos + 24)
    snippet = raw[left:right].replace("\n", "\\n").replace("\r", "\\r")
    if left > 0:
        snippet = "…" + snippet
    if right < len(raw):
        snippet = snippet + "…"
    detail = (exc.msg or "JSON decode error").strip()
    technical = (
        f"工具 '{tool_name}' 的参数不是合法 JSON（{detail}；失败位置 {pos}，附近片段："
        f"{snippet}）。"
    )
    if tool_name in _WRITE_PARSE_TOOLS:
        truncated = "Unterminated string" in detail or (
            isinstance(exc.pos, int) and len(raw) >= 4000 and exc.pos < 200
        )
        trunc_hint = (
            "【信号】输出长度截断导致参数 JSON 未闭合（finish_reason=length 同类）——"
            if truncated
            else "【策略】这通常是整篇正文塞进一次工具调用导致的转义失败——"
        )
        model_msg = (
            technical
            + trunc_hint
            + "不要原样重发整段，也不要再整篇一次 file_write / 大块 str_replace；"
            "改为短骨架 file_write + 按节 file_append / str_replace 分段落盘"
            "（每节远小于一次输出上限）。"
            "勿向用户讲解 JSON 引号转义。"
        )
        return model_msg, _USER_WRITE_PARSE_MSG
    if tool_name in {"delegate", "ask_user"}:
        dual_wrap = (
            "【策略】payload 顶层直接放字段（delegate：`tasks` 或 `playbook`/`playbook_id`），"
            "禁止再包一层 `arguments` 字符串；参数须为单一合法 JSON 对象，"
            "禁止混入 XML/<parameter>/<object> 等协议标签；"
            "按工具 schema 重发精简参数，勿把整篇正文塞进 task 字段"
            "（细则进 deliverable / team_brief）。"
            if tool_name == "delegate"
            else (
                "【策略】参数必须是单一合法 JSON 对象，禁止混入 XML/"
                "<parameter>/<object> 等协议标签；按工具 schema 重发精简参数，"
                "勿把整篇正文塞进参数字段。"
            )
        )
        model_msg = technical + dual_wrap
        return model_msg, model_msg
    model_msg = (
        technical
        + "请修复转义（尤其是字符串内的引号）后，原样重发全部参数；"
        "禁止改写、缩短或删减内容。"
    )
    return model_msg, model_msg


async def execute_tools(
    tool_calls: list[ToolCall],
    registry: ToolRegistry,
    context: ToolContext,
    sink: EventSink,
    *,
    approval_gate: ApprovalGate | None = None,
    citation_sink: list[dict[str, Any]] | None = None,
    annotate_citations: bool = True,
    turn_evidence_ledger: EvidenceLedgerCore | None = None,
    ledger_registrant: str = "",
    run_id: str = "",
    role: str = "",
    allowed_tool_names: list[str] | None = None,
) -> tuple[list[LLMMessage], ToolResult | None, list[ToolAttempt]]:
    """Execute tool calls (parallel, capped).

    Returns ``(tool_messages, terminal, attempts)`` where ``terminal`` is the
    chosen terminal-effect ToolResult (a tool that already produced the turn's
    final answer — handoff / ask_user-stop — or a SUSPEND pause) or ``None``, and
    ``attempts`` carries the per-call fingerprint + success used by convergence
    governance to detect mechanical loops. When multiple terminals appear in one
    round, SUSPEND wins (durable pause must not lose to call-order luck) and a
    warning is logged; normal agent toolsets never hold both classes.

    ``allowed_tool_names`` is the run's least-privilege allow-list (``None`` = no
    restriction). Schema offering already filters to this list; this parameter
    **also enforces at execute** so a model cannot land side effects by calling a
    registered tool that was never granted (e.g. debater ``file_write``).

    When ``citation_sink`` is provided, web sources surfaced by successful research
    tools are merged into it (arrival order, deduped, capped) — **池语义不变**。
    When ``turn_evidence_ledger`` is set, the same hits are also registered into the
    turn-shared ledger (except ``blocked``); tool messages get ``#rN=url`` stable-id
    annotation for both CEO and workers (引用即出处 P1). Without a ledger,
    ``annotate_citations`` keeps the legacy ``[n]=url`` CEO path.

    Display/trace split for ``role == "captain"``: SSE tool events omit ``run_id``
    so the UI renders them as turn-level inline steps (same as captain
    ``content_delta``); ``ToolCallFact`` and circuit-breaker audit still keep
    ``run_id`` for §8.3 fold / audit. Workers keep ``run_id`` on SSE too.

    Same-round parallel ``file_read`` calls that share a normalized path execute
    the underlying read once; sibling tool_calls receive fan-out clones (one
    count bump when the shared result is a full read).
    """
    # Captain self-tools: inline timeline (no run_id on wire); facts/audit keep run_id.
    event_run_id = "" if role == "captain" else run_id
    allowed_set = None if allowed_tool_names is None else frozenset(allowed_tool_names)
    # Same-round file_read path coalesce (leader Future → fan-out clones).
    file_read_inflight: dict[str, asyncio.Future[ToolResult]] = {}

    async def _run_one(
        tc: ToolCall,
    ) -> tuple[LLMMessage, ToolResult | None, ToolAttempt, list[dict[str, Any]]]:
        raw_name = tc.function.name or ""
        name = sanitize_tool_name(raw_name)
        # Mutate in place so transcript / debrief harvest see the cleaned name
        # (same ToolCall objects live on the assistant message).
        if name != raw_name:
            tc.function.name = name
            logger.info(
                "tool.name_protocol_sanitized",
                tool_call_id=tc.id,
                raw_name=raw_name[:120],
                cleaned_name=name[:80],
            )
        raw_args = tc.function.arguments or ""
        # Strip vendor/XML protocol residue before parse so hybrid leaks
        # (``{"tasks"><parameter…>``) become retryable JSON when salvageable.
        parse_args = sanitize_raw_tool_arguments(raw_args)
        if parse_args != raw_args:
            with contextlib.suppress(TypeError, ValueError):
                tc.function.arguments = parse_args
            raw_args = parse_args
        fingerprint = fingerprint_tool_call(name, raw_args)
        parse_exc: json.JSONDecodeError | None = None
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError as exc:
            parse_exc = exc
            salvaged = salvage_handoff_raw_arguments(raw_args, tool_name=name or raw_name)
            if salvaged is not None:
                # Guaranteed loadable object by salvage; continue as a normal parse.
                args = json.loads(salvaged)
                parse_exc = None
                logger.info(
                    "tool.args_salvaged",
                    tool=name or raw_name,
                    tool_call_id=tc.id,
                    args_preview=salvaged[:200],
                )
                with contextlib.suppress(TypeError, ValueError):
                    tc.function.arguments = salvaged
                raw_args = salvaged
                fingerprint = fingerprint_tool_call(name, raw_args)
        if parse_exc is not None:
            model_msg, user_msg = _format_args_parse_error(
                name or raw_name, raw_args, parse_exc
            )
            # Honest wire pair: marker args (not ``{}``) + error end — never run the tool.
            # UI/process line gets人话 for write tools; model transcript keeps technical tip.
            sink.emit(
                tool_use_start(
                    tc.id, name or raw_name, dict(_ARGS_PARSE_FAILED_MARKER), run_id=event_run_id
                )
            )
            sink.emit(
                tool_use_end(
                    tc.id,
                    name or raw_name,
                    success=False,
                    output=user_msg,
                    run_id=event_run_id,
                )
            )
            logger.info(
                "tool.args_parse_failed",
                tool=name or raw_name,
                tool_call_id=tc.id,
                pos=parse_exc.pos,
                msg=parse_exc.msg,
                args_preview=raw_args[:200],
            )
            logger.info(
                "tool.execute_end",
                tool=name or raw_name,
                status="args_parse_failed",
                duration_ms=0,
            )
            return (
                _failed_tool_message(tc.id, model_msg),
                None,
                ToolAttempt(
                    fingerprint,
                    name or raw_name,
                    success=False,
                    parse_failure=True,
                    error_summary=model_msg,
                    meta={"error_class": ERROR_CLASS_VALIDATION},
                ),
                [],
            )

        if isinstance(args, dict):
            if name == "delegate":
                unwrapped = unwrap_nested_delegate_arguments(args)
                if unwrapped is not None:
                    logger.info(
                        "tool.delegate_arguments_unwrapped",
                        tool_call_id=tc.id,
                        inner_keys=sorted(unwrapped.keys())[:20],
                        has_tasks=isinstance(unwrapped.get("tasks"), list)
                        and bool(unwrapped.get("tasks")),
                        has_playbook=bool(
                            (
                                isinstance(unwrapped.get("playbook"), str)
                                and str(unwrapped.get("playbook") or "").strip()
                            )
                            or (
                                isinstance(unwrapped.get("playbook_id"), str)
                                and str(unwrapped.get("playbook_id") or "").strip()
                            )
                        ),
                    )
                    args = unwrapped
                    with contextlib.suppress(TypeError, ValueError):
                        tc.function.arguments = json.dumps(args, ensure_ascii=False)
            cleaned_args = sanitize_tool_args(args)
            if cleaned_args != args:
                args = cleaned_args
                with contextlib.suppress(TypeError, ValueError):
                    tc.function.arguments = json.dumps(args, ensure_ascii=False)

        sink.emit(tool_use_start(tc.id, name, args, run_id=event_run_id))
        if event_run_id:
            sink.emit(
                run_phase(
                    event_run_id,
                    getattr(context, "agent_id", "") or event_run_id,
                    "tool",
                    tool_name=name or raw_name or None,
                )
            )

        if allowed_set is not None and name not in allowed_set:
            if name in _FILE_PRODUCT_TOOL_NAMES:
                # 白名单限制：说明限制即可；禁止劝「handoff 正文交差」冒充写盘。
                error_msg = (
                    f"工具 '{name}' 不在本 run 的允许列表中，未执行。"
                    "本回合未授权该写盘工具；请改用已提供的工具，或 escalate / "
                    "handoff 说明缺写盘权限（勿用正文冒充落盘）。"
                )
                deny_status = "allowlist_deny"
            else:
                error_msg = (
                    f"工具 '{name}' 不在本 run 的允许列表中，未执行。"
                    "请仅使用当前已提供的工具，不要调用未授权的写盘或其他副作用工具。"
                )
                deny_status = "allowlist_deny"
            sink.emit(
                tool_use_end(
                    tc.id, name or raw_name, success=False, output=error_msg, run_id=event_run_id
                )
            )
            logger.info(
                "tool.execute_end",
                tool=name or raw_name,
                status=deny_status,
                duration_ms=0,
                reason=error_msg,
            )
            return (
                _failed_tool_message(tc.id, error_msg),
                None,
                ToolAttempt(
                    fingerprint,
                    name or raw_name,
                    success=False,
                    policy_failure=True,
                    error_summary=error_msg,
                    meta=_attempt_meta_with_landing_path(
                        name or raw_name,
                        args,
                        {
                            "error_class": ERROR_CLASS_PERMISSION,
                            "permission_kind": "allowlist",
                        },
                    ),
                ),
                [],
            )

        tool = registry.get_optional(name) if name else None
        if tool is None:
            missing = name or raw_name
            error_msg, status, policy_failure = _missing_tool_feedback(
                missing, raw_name=raw_name, registry=registry
            )
            sink.emit(
                tool_use_end(
                    tc.id,
                    name or raw_name,
                    success=False,
                    output=error_msg,
                    run_id=event_run_id,
                )
            )
            logger.info(
                "tool.execute_end",
                tool=name or raw_name,
                status=status,
                duration_ms=0,
            )
            return (
                _failed_tool_message(tc.id, error_msg),
                None,
                ToolAttempt(
                    fingerprint,
                    name or raw_name,
                    success=False,
                    policy_failure=policy_failure,
                    error_summary=error_msg,
                    meta=_attempt_meta_with_landing_path(name or raw_name, args),
                ),
                [],
            )

        # P3 safety circuit breaker — last-line heuristic (not a security boundary).
        # full_trust / kickoff / turn grants never override FORCE_APPROVAL or DENY.
        from agentcore.runtime.safety_breaker import BreakerVerdict, evaluate_tool_call

        breaker = evaluate_tool_call(name, args)
        if breaker is not None and breaker.verdict is BreakerVerdict.DENY:
            from agentcore.runtime.audit.hooks import on_circuit_breaker

            on_circuit_breaker(
                tool_name=name,
                tool_call_id=tc.id,
                rule_id=breaker.rule_id,
                verdict=breaker.verdict.value,
                reason=breaker.reason,
                run_id=run_id or None,
            )
            denial = (
                f"工具 '{name}' 被安全熔断拒绝：{breaker.reason}"
                "请改用其他方案，不要原样重试该路径。"
            )
            sink.emit(
                tool_use_end(tc.id, name, success=False, output=denial, run_id=event_run_id)
            )
            logger.info(
                "tool.execute_end",
                tool=name,
                status="circuit_breaker_deny",
                rule_id=breaker.rule_id,
                duration_ms=0,
            )
            return (
                _failed_tool_message(tc.id, denial),
                None,
                ToolAttempt(
                    fingerprint,
                    name,
                    success=False,
                    policy_failure=True,
                    meta=_attempt_meta_with_landing_path(name, args),
                ),
                [],
            )

        force_breaker = (
            breaker is not None and breaker.verdict is BreakerVerdict.FORCE_APPROVAL
        )
        if force_breaker:
            from agentcore.runtime.audit.hooks import on_circuit_breaker

            on_circuit_breaker(
                tool_name=name,
                tool_call_id=tc.id,
                rule_id=breaker.rule_id,
                verdict=breaker.verdict.value,
                reason=breaker.reason,
                run_id=run_id or None,
            )
            # Surface a preview-only hint on the approval card (arguments are already
            # truncated for SSE; tools execute the original ``args`` unchanged).
            args_for_gate = {
                **args,
                "circuit_breaker_hint": breaker.reason,
            }
        else:
            args_for_gate = args

        needs_approval = force_breaker or (
            approval_gate is not None
            and tool_call_requires_approval(name, tool.schema.approval, args)
        )
        # CEO 短操作：captain 直调 browser_*（navigate/click/type/scroll/snapshot）
        # 不弹审批（force_breaker 仍拦）；screenshot 仅 worker，不走本分支。
        if (
            needs_approval
            and not force_breaker
            and role == "captain"
            and name.startswith("browser_")
            and name != "browser_screenshot"
        ):
            needs_approval = False
        # Cloud *workers* historically ungated for server-sandbox tools. When
        # resolve_worker_gate shares the turn gate only for MCP/Host, narrow
        # prompts to desktop-touch tools (file_write etc. stay ungated on cloud
        # root). CEO / captain always keep full GRANTABLE gating — do not key
        # off backend.location alone.
        if (
            needs_approval
            and not force_breaker
            and approval_gate is not None
            and role == "worker"
        ):
            from agentcore.runtime.sandbox_approval import (
                is_desktop_touch_tool,
                worker_gate_applies,
            )

            if not worker_gate_applies(context.backend) and not is_desktop_touch_tool(
                name
            ):
                needs_approval = False
        if needs_approval:
            from agentcore.runtime.sandbox_approval import execution_tool_auto_passes

            if approval_gate is None:
                # Forced destructive shape but no human gate available — fail closed.
                denial = (
                    f"工具 '{name}' 触发安全熔断且当前路径无法人工确认，已拒绝执行。"
                    f"{breaker.reason if breaker else ''}"
                    "请改用其他方案。"
                )
                sink.emit(
                    tool_use_end(
                        tc.id, name, success=False, output=denial, run_id=event_run_id
                    )
                )
                logger.info(
                    "tool.execute_end",
                    tool=name,
                    status="circuit_breaker_no_gate",
                    duration_ms=0,
                )
                return (
                    _failed_tool_message(tc.id, denial),
                    None,
                    ToolAttempt(
                        fingerprint,
                        name,
                        success=False,
                        policy_failure=True,
                        meta=_attempt_meta_with_landing_path(name, args),
                    ),
                    [],
                )

            auto_pass = (not force_breaker) and execution_tool_auto_passes(
                context.backend, name, permission_axes=approval_gate.permission_axes
            )
            # INFO（非 debug）：round_end 后若长时间无 execute_end，靠此定位卡在审批还是执行。
            # will_prompt peeks kickoff/session/_granted/_denied short-circuits so
            # awaiting_approval is not true when authorize would silently pass.
            awaiting_approval = (not auto_pass) and approval_gate.will_prompt(
                tool_name=name,
                arguments=args_for_gate,
                execution_id=context.execution_id,
                force=force_breaker,
            )
            logger.info(
                "tool.execute_start",
                tool=name,
                tool_call_id=tc.id,
                run_id=run_id or "",
                awaiting_approval=awaiting_approval,
            )
            if auto_pass:
                logger.info("approval.sandbox_auto_pass", tool=name)
            else:
                decision = await approval_gate.authorize(
                    tool_name=name,
                    tool_call_id=tc.id,
                    arguments=args_for_gate,
                    execution_id=context.execution_id,
                    force=force_breaker,
                )
                if decision is ApprovalDecision.DENY:
                    # Denial is a governance signal (user refuse / timeout), not an execution
                    # failure — mark policy_failure so the run-scoped circuit breaker ignores it.
                    denial = (
                        f"工具 '{name}' 未获用户授权，该操作未执行。"
                        "请改用其他方案或询问如何继续，不要再调用此工具。"
                    )
                    sink.emit(
                        tool_use_end(
                            tc.id, name, success=False, output=denial, run_id=event_run_id
                        )
                    )
                    logger.info("tool.execute_end", tool=name, status="denied", duration_ms=0)
                    return (
                        _failed_tool_message(tc.id, denial),
                        None,
                        ToolAttempt(
                            fingerprint,
                            name,
                            success=False,
                            policy_failure=True,
                            meta=_attempt_meta_with_landing_path(name, args),
                        ),
                        [],
                    )
        else:
            logger.info(
                "tool.execute_start",
                tool=name,
                tool_call_id=tc.id,
                run_id=run_id or "",
                awaiting_approval=False,
            )

        # 检索预算 (提案 A1): reserve a per-run slot immediately before execute so
        # approval / breaker denials never consume budget. Orthogonal to
        # LoopController.investigation_calls / team_gate.
        from agentcore.runtime.runs.retrieval_budget import (
            RETRIEVAL_TOOL_NAMES,
            budget_exhausted_output,
            charges_retrieval_budget,
        )

        budget_state = context.retrieval_budget
        budget_reserved = False
        if name in RETRIEVAL_TOOL_NAMES and budget_state is not None:
            if not await budget_state.try_reserve():
                exhausted = budget_exhausted_output()
                sink.emit(
                    tool_use_end(
                        tc.id, name, success=False, output=exhausted, run_id=event_run_id
                    )
                )
                logger.info(
                    "tool.execute_end",
                    tool=name,
                    status="retrieval_budget_exhausted",
                    duration_ms=0,
                    retrieval_budget_limit=budget_state.limit,
                    retrieval_budget_used=budget_state.used,
                )
                return (
                    _failed_tool_message(tc.id, exhausted),
                    None,
                    ToolAttempt(
                        fingerprint,
                        name,
                        success=False,
                        error_summary=exhausted,
                        meta=_attempt_meta_with_landing_path(
                            name,
                            args,
                            {
                                "error_class": ERROR_CLASS_PERMANENT,
                                "code": "retrieval_budget_exhausted",
                                "retire_tools": sorted(RETRIEVAL_TOOL_NAMES),
                                "retire_message": (
                                    "检索预算已尽：web_search / read_url 本回合已停用——"
                                    "请基于已有材料交付，禁止再调用检索工具。"
                                ),
                            },
                        ),
                    ),
                    [],
                )
            budget_reserved = True

        # 工具执行阶段进度 (联网搜索前端展示优化): inject a per-call phase callback so a
        # long-running tool (web_search) can report a coarse EXECUTION phase mid-flight. The
        # executor owns event shape (引擎纯化) — the tool passes only a phase token; we close
        # over this call's id/name/event_run_id and emit the transport-only ``tool_use_progress``.
        def _emit_phase(phase: str) -> None:
            sink.emit(tool_use_progress(tc.id, name, phase, run_id=event_run_id))

        def _emit_progress(phase: str, data: dict[str, Any] | None = None) -> None:
            sink.emit(tool_use_progress(tc.id, name, phase, run_id=event_run_id, extra=data))

        ctx = replace(context, on_phase=_emit_phase, on_progress=_emit_progress)

        started = time.monotonic()
        timeout = resolve_tool_timeout(tool.schema, args)
        deadline_token = set_tool_deadline(timeout)
        coalesce_key = (
            _file_read_round_coalesce_key(args) if name == "file_read" else None
        )
        try:
            if coalesce_key is not None:
                existing = file_read_inflight.get(coalesce_key)
                if existing is not None:
                    shared = await existing
                    result = _clone_tool_result(shared, tc.id)
                    result.duration_ms = int((time.monotonic() - started) * 1000)
                else:
                    fut: asyncio.Future[ToolResult] = (
                        asyncio.get_running_loop().create_future()
                    )
                    file_read_inflight[coalesce_key] = fut
                    try:
                        if timeout is None:
                            result = await tool.execute(args, ctx)
                        else:
                            result = await asyncio.wait_for(
                                tool.execute(args, ctx), timeout
                            )
                        # Snapshot before this call mutates ``tool_call_id``.
                        if not fut.done():
                            fut.set_result(replace(result))
                    except Exception as exc:
                        if not fut.done():
                            fut.set_exception(exc)
                        raise
            elif timeout is None:
                result = await tool.execute(args, ctx)
            else:
                result = await asyncio.wait_for(tool.execute(args, ctx), timeout)
        except TimeoutError:
            # B1 backstop: the call blew its ceiling. wait_for has already cancelled
            # the tool coroutine (a cancel-safe tool releases its side effects in
            # turn — e.g. the sandbox kills its subprocess); surface a model-facing
            # error so the loop adapts instead of hanging, and count it as a failed
            # attempt so a tool that keeps timing out trips convergence governance.
            # Liveness (hang) ≠ capacity contract — steer forbids identical retry.
            if budget_reserved and budget_state is not None:
                await budget_state.refund()
            duration_ms = int((time.monotonic() - started) * 1000)
            ceiling = timeout if timeout is not None else 0.0
            timeout_msg = (
                f"工具 '{name}' 活性挂起：超过 {ceiling:.0f}s 仍无响应，已中止。"
                "这不是字节/行数触顶——请缩小处理范围、换路径策略或换工具；"
                "禁止原样重试同一次调用。"
            )
            sink.emit(
                tool_use_end(
                    tc.id, name, success=False, output=timeout_msg, run_id=event_run_id
                )
            )
            timeout_fields: dict[str, Any] = {
                "tool": name,
                "status": "timeout",
                "duration_ms": duration_ms,
                "timeout_layer": "outer",
                "liveness_timeout": True,
            }
            if name == "git" and isinstance(args.get("subcommand"), str):
                timeout_fields["subcommand"] = args["subcommand"]
            logger.warning("tool.execute_end", **timeout_fields)
            return (
                _failed_tool_message(tc.id, timeout_msg),
                None,
                ToolAttempt(
                    fingerprint,
                    name,
                    success=False,
                    error_summary=timeout_msg,
                    meta=_attempt_meta_with_landing_path(
                        name,
                        args,
                        {
                            "liveness_timeout": True,
                            "timeout_layer": "outer",
                            "error_class": ERROR_CLASS_PERMANENT,
                        },
                    ),
                ),
                [],
            )
        except Exception as e:
            # Per-tool exception firewall (audit/05 P2-1): a crash in one parallel call
            # must not cancel its siblings via asyncio.gather. Convert to a failed tool
            # result so the loop can adapt; SUSPEND terminals are unaffected (they return
            # normally, never raise).
            if budget_reserved and budget_state is not None:
                await budget_state.refund()
            duration_ms = int((time.monotonic() - started) * 1000)
            # Always carry the exception type: some builtins (e.g. NotImplementedError)
            # stringify to "" and the model would see a blank reason and retry blindly.
            detail = str(e).strip()
            detail = f"{type(e).__name__}: {detail}" if detail else type(e).__name__
            error_msg = (
                f"工具 '{name}' 执行时发生内部错误：{detail}。"
                "请调整方案或换一种方式，不要原样重试。"
            )
            sink.emit(
                tool_use_end(tc.id, name, success=False, output=error_msg, run_id=event_run_id)
            )
            logger.exception(
                "tool.execute_end",
                tool=name,
                status="crash",
                duration_ms=duration_ms,
            )
            return (
                _failed_tool_message(tc.id, error_msg),
                None,
                ToolAttempt(
                    fingerprint,
                    name,
                    success=False,
                    error_summary=error_msg,
                    meta=_attempt_meta_with_landing_path(name, args),
                ),
                [],
            )
        finally:
            reset_tool_deadline(deadline_token)
        result.tool_call_id = tc.id

        # 缓存命中 / A3 拒绝等不计预算：reserved slot refunded when not charged.
        if budget_reserved and budget_state is not None and not charges_retrieval_budget(result):
            await budget_state.refund()

        if result.success:
            output = result.output
        else:
            # Surface BOTH the terse error summary AND any diagnostic output
            # (stdout/stderr for code_execute) so the model can self-correct
            # instead of debugging blind: many tools put the real reason in
            # ``output``, not the short ``error`` (e.g. code_execute's error is
            # just "退出码 N" while the traceback / "command not found" lives in
            # output). Either may be empty; join the non-empty parts.
            # Identical error+output (common when tools mirror the same string)
            # must not double the model-visible failure text.
            err_part = (result.error or "").strip()
            out_part = (result.output or "").strip()
            if err_part and out_part and err_part == out_part:
                output = err_part
            else:
                output = "\n".join(p for p in (err_part, out_part) if p) or "Unknown error"
        # 挂起即收口: a SUSPEND terminal already persisted its *_required card in the
        # pause snapshot. Emitting a durable tool_use_end here would append a fact that
        # diverges snapshot vs DB (and the call stays PENDING — no tool_call fact either).
        # Live UI already has the interaction card; skip the end event entirely.
        if result.effect is not ToolEffect.SUSPEND:
            sink.emit(
                tool_use_end(
                    tc.id,
                    name,
                    success=result.success,
                    output=output,
                    display=result.display,
                    run_id=event_run_id,
                )
            )
        # 检索观测：web_search 把 query / hosts 放进 metadata，转发到 execute_end
        # 以便从统一工具结束事件还原「搜了什么 / 命中哪些域」。
        end_fields: dict[str, Any] = {
            "tool": name,
            "status": "ok" if result.success else "error",
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        if not result.success:
            # Short aggregable failure reason (status=error only). Full text stays on
            # tool_use_end.output / transcript; logs need a greppable tip without adjacent
            # event archaeology.
            end_fields["reason"] = _short_tool_error_reason(output)
        meta = result.metadata or {}
        if isinstance(meta.get("query"), str) and meta["query"]:
            end_fields["query"] = meta["query"]
        if isinstance(meta.get("hosts"), list):
            end_fields["hosts"] = meta["hosts"]
        if isinstance(meta.get("blocked_hosts"), list) and meta["blocked_hosts"]:
            end_fields["blocked_hosts"] = meta["blocked_hosts"]
        if isinstance(meta.get("subcommand"), str) and meta["subcommand"]:
            end_fields["subcommand"] = meta["subcommand"]
        if isinstance(meta.get("timeout_layer"), str) and meta["timeout_layer"]:
            end_fields["timeout_layer"] = meta["timeout_layer"]
        logger.info("tool.execute_end", **end_fields)

        citations = result.citations if (result.success and result.citations) else []
        # 执行层失败打机器尾注（仅 transcript；SSE 上文仍用无 marker 的 output）。
        msg_content = output if result.success else with_tool_failed_marker(output or "")
        message = LLMMessage(role="tool", content=msg_content, tool_call_id=tc.id)
        policy_failure = bool(result.metadata.get("policy_failure"))
        # 参数契约拒绝 (tools/protocol.py): forward the tool's self-correctable-rejection
        # marker so the run-scoped circuit breaker skips it (loop_controller.record).
        contract_failure = bool(result.contract_failure)
        error_summary = ""
        if not result.success and not policy_failure:
            error_summary = output if isinstance(output, str) else ""
        result_meta = dict(result.metadata) if result.metadata else {}
        if not result.success and "error_class" not in result_meta:
            if result_meta.get("retire_tools") or result_meta.get("liveness_timeout"):
                result_meta["error_class"] = ERROR_CLASS_PERMANENT
            elif policy_failure:
                result_meta["error_class"] = ERROR_CLASS_PERMISSION
            elif contract_failure:
                result_meta["error_class"] = ERROR_CLASS_VALIDATION
        return (
            message,
            (result if result.is_terminal else None),
            ToolAttempt(
                fingerprint,
                name,
                success=result.success,
                policy_failure=policy_failure,
                contract_failure=contract_failure,
                error_summary=error_summary,
                meta=_attempt_meta_with_landing_path(
                    name,
                    args,
                    result_meta or None,
                    error=error_summary,
                    contract_failure=contract_failure,
                ),
            ),
            citations,
        )

    sem = asyncio.Semaphore(MAX_PARALLEL_TOOLS)

    async def _bounded(
        tc: ToolCall,
    ) -> tuple[LLMMessage, ToolResult | None, ToolAttempt, list[dict[str, Any]]]:
        async with sem:
            return await _run_one(tc)

    # Same-batch handoff after writes: ``landed_artifact_kinds`` is a shared dict, but
    # parallel gather can still let handoff observe an empty stamp if it races ahead of
    # file_write/file_append. Run non-handoff tools first (still parallel among
    # themselves), then handoff — message order stays call-list order below.
    def _is_handoff_call(tc: ToolCall) -> bool:
        return sanitize_tool_name(tc.function.name or "") == "handoff"

    has_handoff = any(_is_handoff_call(tc) for tc in tool_calls)
    has_non_handoff = any(not _is_handoff_call(tc) for tc in tool_calls)
    if has_handoff and has_non_handoff:
        by_id: dict[
            str, tuple[LLMMessage, ToolResult | None, ToolAttempt, list[dict[str, Any]]]
        ] = {}
        first = [tc for tc in tool_calls if not _is_handoff_call(tc)]
        second = [tc for tc in tool_calls if _is_handoff_call(tc)]
        for tc, quad in zip(
            first, await asyncio.gather(*[_bounded(tc) for tc in first]), strict=True
        ):
            by_id[tc.id] = quad
        for tc, quad in zip(
            second, await asyncio.gather(*[_bounded(tc) for tc in second]), strict=True
        ):
            by_id[tc.id] = quad
        quads = [by_id[tc.id] for tc in tool_calls]
    else:
        quads = await asyncio.gather(*[_bounded(tc) for tc in tool_calls])

    # 挂起即收口 (②): a SUSPEND terminal leaves its call PENDING — the suspended tool_call
    # gets NO result message AND NO §8.3 tool_call fact (recorded below), so the resumed
    # window ends exactly at the assistant (the fold reads the missing result as「still
    # pending」). This reproduces the shape the old blocking pause produced by never
    # returning from ``execute``. INTERACT / HANDOFF differ: they DID produce the turn's
    # answer, so they keep their tool message + fact like any completed call.
    def _suspends(t: ToolResult | None) -> bool:
        return t is not None and t.effect is ToolEffect.SUSPEND

    messages = [m for m, t, _, _ in quads if not _suspends(t)]
    # Terminal selection: prefer SUSPEND over HANDOFF/INTERACT when a round somehow
    # yields multiple terminals (defense — normal agent toolsets never hold both).
    # A durable pause must not be overridden by call-order luck with a non-SUSPEND
    # terminal in the same gather batch. Warn when more than one terminal appears.
    terminals = [t for _, t, _, _ in quads if t is not None]
    if len(terminals) > 1:
        logger.warning(
            "tool.multi_terminal",
            count=len(terminals),
            effects=[t.effect.value for t in terminals],
        )
    terminal = next((t for t in terminals if t.effect is ToolEffect.SUSPEND), None)
    if terminal is None and terminals:
        terminal = terminals[0]
    attempts = [a for _, _, a, _ in quads]

    # Merge web sources into mid-turn sink (deterministic call order) for pause /
    # legacy ``[n]``；台账登记 ``#rN`` 并 annotate。P2：用户可见卡由 settle 按
    # ``cited_ids`` 投影，不在此发射 ``citations_event``。
    if citation_sink is not None or turn_evidence_ledger is not None:
        for message, _terminal, _attempt, message_citations in quads:
            if not message_citations:
                continue
            if citation_sink is not None:
                numbers = merge_citations(citation_sink, message_citations)
            else:
                numbers = {}
            if turn_evidence_ledger is not None and ledger_registrant:
                id_map = await _register_message_citations(
                    turn_evidence_ledger,
                    message_citations,
                    registrant=ledger_registrant,
                )
                message.content = annotate_ledger_ids(
                    message.content or "", message_citations, id_map
                )
            elif annotate_citations:
                message.content = annotate_tool_citations(
                    message.content or "", message_citations, numbers
                )
        # Live 台账增量：本轮登记后 drain → 独立通道（不占 citations_event）。
        if turn_evidence_ledger is not None:
            emit_ledger_delta(sink, turn_evidence_ledger)

    # 执行级事件溯源 (§8.3 / Phase 2 边界①): record each completed call's FINAL
    # model-facing result as a tool_call fact — captured HERE, after the citation
    # annotation above, so it is byte-for-byte what the next round's window carried (the
    # forwarded tool_use_end fires inside _run_one with the pre-annotation text). The
    # window fold reads tool results from these facts. ``tool_calls`` is positionally
    # aligned with ``quads`` (asyncio.gather preserves order), so zip pairs each result
    # to its issuing call. A SUSPEND call is skipped (挂起即收口 ②): recording its fact
    # would inject a phantom result into the resumed window — matching the old blocking
    # pause, where ``gather`` never returned so no fact was recorded for the parked call.
    for tc, (message, terminal_q, attempt, _citations) in zip(tool_calls, quads, strict=False):
        if _suspends(terminal_q):
            continue
        record_turn_fact(
            ToolCallFact(
                run_id=run_id,
                tool_call_id=message.tool_call_id or tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments or "",
                result=message.content or "",
                success=attempt.success,
            ).to_fact()
        )

    return messages, terminal, attempts


async def _register_message_citations(
    ledger: EvidenceLedgerCore,
    citations: list[dict[str, Any]],
    *,
    registrant: str,
) -> dict[str, str]:
    """向回合共享台账登记本条工具结果的来源；返回 ``{归一化url: #rN}``。"""
    id_map: dict[str, str] = {}
    for c in citations:
        eid = await ledger.register_citation(c, registrant=registrant)
        if eid is None:
            continue
        key = normalize_citation_url(str(c.get("url") or ""))
        if key:
            id_map[key] = eid
    return id_map
