"""Conformance vector — browser (worker browser_* + login escalate).

A worker drives the browser surface (navigate → snapshot → click → screenshot).
Each ``tool_use_end`` carries the shared ``display`` contract
(``kind:"browser"`` + action/url/title/detail/frame) — DURABLE, so it folds into
that run's ``process`` and the desktop/mobile activity card rebuilds verbatim on
reload/journal replay. Pins: worker browser tool steps carry ``display`` into
``run.process`` (not the CEO bubble); state-changing steps + screenshot carry a
key-frame ``frame`` (``browser/step-NNNN.jpg``), the read-only snapshot does not.

A second scene stops after browser steps at a pending ``escalation_required`` with
``browser_login=true`` (for shoot / EscalationCard auto-reveal).

See ``vectors/__init__.py`` for the aggregated ``VECTORS`` registry.
"""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    escalation_required,
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
_LOGIN_SITE = "https://example.com/login"
_LOGIN_Q = "目标站点需要登录才能继续调研，请你在浏览器里完成登录。"
_LOGIN_A = "用户已登录，继续抓取"


def _bd(action: str, *, title: str = "", detail: str = "", frame: str = "", url: str = _SITE) -> dict:
    """One browser step's DURABLE display (shared frontend contract; field names fixed)."""
    d: dict = {"kind": "browser", "action": action, "url": url}
    if title:
        d["title"] = title
    if detail:
        d["detail"] = detail
    if frame:
        d["frame"] = frame
    return d


def _browser_worker_prefix() -> list[SSEEvent]:
    """Shared lead-in: delegate + run_plan + navigate/snapshot (worker r1)."""
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
    ]


def _multi_agent_browser_session() -> list[SSEEvent]:
    return [
        *_browser_worker_prefix(),
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


def _multi_agent_browser_login_pending() -> list[SSEEvent]:
    """Worker 浏览器后撞登录墙 → pending ``escalation_required(browser_login=true)``。

    流到此为止（无 resolve / message_end），供 shoot 看 EscalationCard「需要你登录」+
    自动揭示右坞浏览器壳。前置 navigate→login 页 + snapshot，保证活动卡/直播入口也有素材。
    """
    return [
        *_browser_worker_prefix(),
        # 点进登录页 → 关键帧
        tool_use_start("b3", "browser_click", {"ref": "e-login", "snapshot_version": 1}, run_id="r1"),
        tool_use_end(
            "b3",
            "browser_click",
            success=True,
            output='{"action":"click","final_url":"https://example.com/login"}',
            display=_bd(
                "click",
                title="Sign in",
                detail="点击登录入口",
                frame="browser/step-0002.jpg",
                url=_LOGIN_SITE,
            ),
            run_id="r1",
        ),
        tool_use_start("b4", "browser_snapshot", {}, run_id="r1"),
        tool_use_end(
            "b4",
            "browser_snapshot",
            success=True,
            output='{"action":"snapshot","snapshot_version":2,"untrusted_web_content":{"source_url":"https://example.com/login"}}',
            display=_bd(
                "snapshot",
                title="Sign in",
                detail="读取登录页结构（v2）",
                url=_LOGIN_SITE,
            ),
            run_id="r1",
        ),
        # 阻塞挂起：browser_login=true → 桌面 EscalationCard 登录卡 + 自动 reveal 浏览器壳
        escalation_required(
            "r1",
            "w1",
            escalation_id="esc-browser-login",
            question=_LOGIN_Q,
            assumption=_LOGIN_A,
            browser_login=True,
        ),
    ]
