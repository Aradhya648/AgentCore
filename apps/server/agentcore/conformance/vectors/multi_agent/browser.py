"""Conformance vector — L3 团队浏览器 (M0) worker browser session.

A worker drives the six-tool browser surface (navigate → snapshot → click →
screenshot). Each ``tool_use_end`` carries the shared ``display`` contract
(``kind:"browser"`` + action/url/title/detail/frame) — DURABLE, so it folds into
that run's ``process`` and the desktop/mobile activity card rebuilds verbatim on
reload/journal replay. Pins: worker browser tool steps carry ``display`` into
``run.process`` (not the CEO bubble); state-changing steps + screenshot carry a
key-frame ``frame`` (``browser/step-NNNN.jpg``), the read-only snapshot does not.

See ``vectors/__init__.py`` for the aggregated ``VECTORS`` registry.
"""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    message_end,
    message_start,
    run_completed,
    run_output_delta,
    run_plan,
    run_started,
    tool_use_end,
    tool_use_start,
)

from .._common import _CONV, _COST, _USAGE

_SITE = "https://example.com/"


def _bd(action: str, *, title: str = "", detail: str = "", frame: str = "") -> dict:
    """One browser step's DURABLE display (shared frontend contract; field names fixed)."""
    d: dict = {"kind": "browser", "action": action, "url": _SITE}
    if title:
        d["title"] = title
    if detail:
        d["detail"] = detail
    if frame:
        d["frame"] = frame
    return d


def _multi_agent_browser_session() -> list[SSEEvent]:
    agents = [
        {
            "id": "w1",
            "role": "调研员",
            "thinking": True,
        },
    ]
    plan_runs = [{"id": "r1", "agent_id": "w1", "task": "用浏览器调研目标网站", "depends_on": []}]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我安排调研员用浏览器实地看一下。"),
        tool_use_start("dc1", "delegate", {"tasks": [{"role": "调研员"}], "coordinate": False}),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="浏览器调研",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        # navigate → 关键帧 step-0001
        tool_use_start("b1", "browser_navigate", {"url": _SITE}, run_id="r1"),
        tool_use_end(
            "b1",
            "browser_navigate",
            success=True,
            output='{"action":"navigate","final_url":"https://example.com/","http_status":200}',
            display=_bd(
                "navigate",
                title="Example Domain",
                detail="打开 https://example.com/（HTTP 200）",
                frame="browser/step-0001.jpg",
            ),
            run_id="r1",
        ),
        # snapshot → 无关键帧（只读）
        tool_use_start("b2", "browser_snapshot", {}, run_id="r1"),
        tool_use_end(
            "b2",
            "browser_snapshot",
            success=True,
            output='{"action":"snapshot","snapshot_version":1,"untrusted_web_content":{"source_url":"https://example.com/"}}',
            display=_bd("snapshot", title="Example Domain", detail="读取页面结构（v1）"),
            run_id="r1",
        ),
        # click → 关键帧 step-0002
        tool_use_start("b3", "browser_click", {"ref": "e1", "snapshot_version": 1}, run_id="r1"),
        tool_use_end(
            "b3",
            "browser_click",
            success=True,
            output='{"action":"click","final_url":"https://example.com/"}',
            display=_bd(
                "click", title="Example Domain", detail="点击元素 e1", frame="browser/step-0002.jpg"
            ),
            run_id="r1",
        ),
        # screenshot → 关键帧 step-0003
        tool_use_start("b4", "browser_screenshot", {}, run_id="r1"),
        tool_use_end(
            "b4",
            "browser_screenshot",
            success=True,
            output='{"action":"screenshot","keyframe":"browser/step-0003.jpg"}',
            display=_bd("screenshot", title="Example Domain", detail="截取当前页面", frame="browser/step-0003.jpg"),
            run_id="r1",
        ),
        run_output_delta("r1", "w1", "已用浏览器完成目标网站调研。"),
        run_completed(
            "r1",
            "w1",
            output_summary="完成网站调研",
            duration_ms=4200,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        tool_use_end("dc1", "delegate", success=True, output="团队完成浏览器调研。"),
        content_delta(" 调研员已实地查看并记录关键帧。"),
        message_end(FinishReason.END_TURN, input_tokens=3200, output_tokens=520, cost=_COST),
    ]
