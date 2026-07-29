"""Worker Escalation Gate: scheme-layer signals after a tool round."""

from __future__ import annotations

from typing import Any

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.events import EventSink, escalation_raised, run_escalation_gate
from agentcore.runtime.routing import evaluate_after_tools, signals_as_dicts


def apply_escalation_gate(
    *,
    attempts: list[Any],
    tool_results: list[LLMMessage],
    sink: EventSink,
    run_id: str,
    agent_id: str,
    gate_escalation_sink: list[dict[str, Any]],
) -> None:
    """Run Escalation Gate after a tool round; emit + accumulate scheme-layer signals."""
    from agentcore.runtime.loop_controller import ToolAttempt

    typed_attempts = [a for a in attempts if isinstance(a, ToolAttempt)]
    outputs = [(m.content or "") for m in tool_results]
    verdict = evaluate_after_tools(
        attempts=typed_attempts,
        tool_outputs=outputs,
        run_id=run_id,
    )
    if not verdict.should_escalate:
        return
    payloads = signals_as_dicts(verdict.signals)
    # Live + harvest 同口径：同 run 内按 question 去重，避免语料误伤/同信号多轮刷屏。
    seen = {str(e.get("question", "")) for e in gate_escalation_sink if e.get("question")}
    unique: list[dict[str, Any]] = []
    for payload in payloads:
        question = str(payload.get("question", ""))
        if not question or question in seen:
            continue
        seen.add(question)
        unique.append(payload)
    if not unique:
        return
    gate_escalation_sink.extend(unique)
    sink.emit(
        run_escalation_gate(
            run_id,
            agent_id,
            layer=verdict.layer.value,
            action=verdict.action,
            signals=unique,
        )
    )
    # Also surface via the existing live escalate banner so the team UI lights up
    # without a separate Gate card (Phase 1).
    for payload in unique:
        sink.emit(
            escalation_raised(
                run_id,
                agent_id,
                question=str(payload.get("question", "")),
                assumption=str(payload.get("assumption", "")),
                blocking=False,
                kind=str(payload.get("kind", "normal")),
            )
        )
