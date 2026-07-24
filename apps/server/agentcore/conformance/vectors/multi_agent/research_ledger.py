"""多 Agent 调研台账通道向量（引用即出处 P1 地基 · P2 语义翻转）。

worker 正文引 ``#rN`` → 汇入后 id 不变 → 独立 ``evidence_ledger`` 通道 +
``citations_event`` = **仅成稿引用集**（含 weak + tier 徽标）。辩论向量不在此文件。
"""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    citations_event,
    content_delta,
    evidence_ledger_event,
    message_end,
    message_start,
    run_completed,
    run_output_delta,
    run_plan,
    run_progress,
    run_started,
    tool_use_end,
    tool_use_start,
)

from .._common import _CONV, _COST, _USAGE


def _multi_agent_research_ledger() -> list[SSEEvent]:
    """Worker 引 #r1/#r3(weak) → CEO 汇入 → 主卡仅引用集；#r2 未引用仅台账痕迹。"""
    agents = [
        {
            "id": "w1",
            "role": "调研员",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研来源", "depends_on": []},
    ]
    ledger_entries = [
        {
            "id": "#r1",
            "url": "https://docs.example.com/guide",
            "title": "官方指南",
            "snippet": "权威说明",
            "site": "docs.example.com",
            "date": "",
            "tier": "official",
            "query": "AgentCore 架构",
            "deep_read": True,
            "registrant": "worker:w1",
            "citable": True,
        },
        {
            "id": "#r2",
            "url": "https://news.example.com/a",
            "title": "媒体报道",
            "snippet": "二手转述",
            "site": "news.example.com",
            "date": "",
            "tier": "media",
            "query": "AgentCore 架构",
            "deep_read": False,
            "registrant": "worker:w1",
            "citable": True,
        },
        {
            "id": "#r3",
            "url": "https://wenku.baidu.com/view/x",
            "title": "弱源笔记",
            "snippet": "低质命中",
            "site": "wenku.baidu.com",
            "date": "",
            "tier": "weak",
            "query": "AgentCore 架构",
            "deep_read": False,
            "registrant": "worker:w1",
            "citable": True,
        },
    ]
    # P2：主卡 = 成稿实际引用（#r1 + weak #r3）；未引用 #r2 不进 citations_event。
    cited_cards = [
        {
            "url": "https://docs.example.com/guide",
            "title": "官方指南",
            "snippet": "权威说明",
            "site": "docs.example.com",
            "id": "#r1",
            "tier": "official",
            "query": "AgentCore 架构",
            "deep_read": True,
            "registrant": "worker:w1",
            "citable": True,
        },
        {
            "url": "https://wenku.baidu.com/view/x",
            "title": "弱源笔记",
            "snippet": "低质命中",
            "site": "wenku.baidu.com",
            "id": "#r3",
            "tier": "weak",
            "query": "AgentCore 架构",
            "deep_read": False,
            "registrant": "worker:w1",
            "citable": True,
        },
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("安排调研。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "调研员"}], "coordinate": False},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="调研来源",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        # Live 台账增量（工具登记后）——含未引用痕迹与 weak。
        evidence_ledger_event(delta=ledger_entries[:2]),
        evidence_ledger_event(delta=[ledger_entries[2]]),
        run_output_delta(
            "r1",
            "w1",
            "据官方指南 #r1 与弱源笔记 #r3，架构采用多 Agent 协作。",
        ),
        run_completed(
            "r1",
            "w1",
            output_summary="完成调研",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
            debrief={
                "summary": "引用官方源 + 显式弱源；一处未引用媒体痕迹",
                "key_points": ["#r1", "#r3"],
            },
        ),
        run_progress(1, 1),
        tool_use_end("dc1", "delegate", success=True, output="调研完成。"),
        # CEO 汇总沿用 worker 正文 id（禁止重写）；显式引用 weak。
        content_delta("综合调研：官方指南 #r1 与弱源 #r3 支持该结论。"),
        # Settle：全量台账 + cited_ids；citations_event = 仅引用集（含 weak tier）。
        evidence_ledger_event(
            entries=ledger_entries,
            cited_ids=["#r1", "#r3"],
        ),
        citations_event(cited_cards),
        message_end(
            FinishReason.END_TURN,
            input_tokens=2400,
            output_tokens=420,
            cost=_COST,
        ),
    ]
