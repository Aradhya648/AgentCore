"""批 C 黄金场六环离线检查器：正/负样本自测（零 LLM / 零 HTTP）。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agentcore.conformance.mlr_golden_rings import (
    BASELINE_DEBATER_SEARCHES,
    EXPECTED_RESEARCH_FILES,
    SEARCH_BUDGET_PER_RUN,
    evaluate_rings,
    extract_topic_keywords,
    format_report,
    motion_preserves_topic,
    prompt_looks_ultra_vague,
    sse_events_to_bundle,
)
from agentcore.conformance.vectors.multi_agent.mlr_debate_acts import (
    _multi_agent_mlr_debate_acts,
)
from agentcore.conformance.vectors.multi_agent.mlr_debate_witness import (
    _multi_agent_mlr_debate_witness,
)
from agentcore.conformance.vectors.multi_agent.stage_card import (
    _multi_agent_stage_card_orphaned,
    _multi_agent_stage_card_start_debate,
)
from agentcore.runtime.events import (
    FinishReason,
    checkpoint_required,
    message_end,
    message_start,
    run_completed,
    run_started,
    tool_use_start,
)

_LV_PROMPT = "茉莉奶白使用四叶花卉图形是否侵犯 LV 商标权，进行模拟法庭"
_TOPIC = "品牌是否应立即终止争议代言联名"

_RESEARCH_FILES = list(EXPECTED_RESEARCH_FILES)
_DEBATE_FILES = [
    "debate/决策简报·终止联名·abcd1234.md",
    "debate/交锋叙事线·终止联名·abcd1234.md",
]

_SERVER_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_RING6 = _SERVER_ROOT / "tests" / "fixtures" / "mlr_golden_ring6_positive.json"

_WITNESS_EXAM = [
    {
        "witness_key": "lens_0",
        "lens_run_id": "lens_0",
        "seat_run_id": "debate_mod_sc_wit_lens_0",
        "name": "证人·法律",
        "origin_caption": "来自幕1·法律",
        "exchanges": [
            {
                "question": "合同第十二条原文如何表述解除条件？",
                "answer": "第十二条写明「严重损害品牌声誉时可单方解除」。",
            }
        ],
        "answer_run_id": "debate_mod_sc_r1_wit_lens_0",
    }
]
_WITNESS_LEDGER = [
    {
        "id": "#e1",
        "url": "",
        "title": "证人·法律：合同第十二条原文如何表述解除条件？",
        "snippet": "第十二条写明「严重损害品牌声誉时可单方解除」。",
        "site": "",
        "date": "",
        "tier": "unknown",
        "side_key": "witness:lens_0",
    }
]
_WITNESSES_ROSTER = [
    {
        "key": "lens_0",
        "name": "证人·法律",
        "lens_run_id": "lens_0",
        "seat_run_id": "debate_mod_sc_wit_lens_0",
        "lens_label": "法律",
        "origin_caption": "来自幕1·法律",
    }
]


def _inject_witness_into_events(events: list) -> list:
    """给 stage_card 骨事件的 debate_result 注入证人点名 + 台账（不改向量文件）。"""
    out = []
    for ev in events:
        if getattr(ev, "type", None) is not None:
            et = str(getattr(ev.type, "value", ev.type) or "")
            payload = dict(getattr(ev, "payload", None) or {})
        elif isinstance(ev, dict):
            et = str(ev.get("type") or "")
            payload = dict(ev.get("payload") or {})
        else:
            out.append(ev)
            continue
        if et == "debate_result":
            payload = {
                **payload,
                "witnesses": list(_WITNESSES_ROSTER),
                "witness_exam": list(_WITNESS_EXAM),
                "evidence_ledger": list(
                    (payload.get("evidence_ledger") or []) + _WITNESS_LEDGER
                ),
                "rounds": [
                    {
                        "round_no": 1,
                        "witness_exam": list(_WITNESS_EXAM),
                        "evidence_ledger_delta": list(_WITNESS_LEDGER),
                    }
                ],
            }
            out.append({"type": et, "payload": payload})
        elif isinstance(ev, dict):
            out.append(ev)
        else:
            out.append(ev)
    return out


def _enrich_stage_card_positive() -> list:
    """以 stage_card 向量为骨，补齐六环所需事件（四透镜 / ask / 案卷 file_read / 证人）。"""
    base = list(_multi_agent_stage_card_start_debate())
    head = [
        message_start("m0", conversation_id="conv_golden"),
        tool_use_start("ask1", "ask_user", {"questions": [{"prompt": "确认启动多视角调研？"}]}),
        checkpoint_required(
            checkpoint_id="ck_ask",
            conversation_id="conv_golden",
            question="是否启动多视角深度调研？",
            questions=[
                {
                    "prompt": "是否启动多视角深度调研？",
                    "options": ["确认启动", "暂不启动"],
                }
            ],
        ),
        message_end(FinishReason.PAUSED, input_tokens=10, output_tokens=5),
        message_start("m1b", conversation_id="conv_golden"),
    ]
    extra_lenses = []
    for rid in ("lens_1", "lens_2", "lens_3"):
        extra_lenses.extend(
            [
                run_started(rid, rid),
                run_completed(
                    rid,
                    rid,
                    output_summary=f"{rid} 完成",
                    duration_ms=100,
                    role="member",
                    model="deepseek-v4-flash",
                ),
            ]
        )
    dossier_tools = [
        tool_use_start(
            "fr1",
            "file_read",
            {"path": "research/汇总与命题卡.md"},
            run_id="debate_mod_sc_r1_pro",
        ),
        tool_use_start(
            "fr2",
            "file_read",
            {"path": "research/法律透镜报告.md"},
            run_id="debate_mod_sc_r1_con",
        ),
        tool_use_start(
            "ws1",
            "web_search",
            {"query": "补缺口"},
            run_id="debate_mod_sc_r1_pro",
        ),
    ]
    return _inject_witness_into_events(head + base + extra_lenses + dossier_tools)


def _positive_bundle():
    return sse_events_to_bundle(
        _enrich_stage_card_positive(),
        user_prompt=_TOPIC,  # 与向量 motion 一致 → 保真
        workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
        conversation_id="conv_golden_pos",
        message_costs={
            "m1": {"total_usd": 1.2},
            "m2": {"total_usd": 3.4},
        },
    )


def _negative_bundle():
    """推进卡 orphan、无 research/、无同图授权 → 多环 FAIL；环6 N/A（无幕2）。"""
    return sse_events_to_bundle(
        _multi_agent_stage_card_orphaned(),
        user_prompt=_LV_PROMPT,  # 超笼统且无 ask → 环1 FAIL
        workspace_files=[],  # 无落盘
        conversation_id="conv_golden_neg",
    )


def test_prompt_vague_and_keywords():
    assert prompt_looks_ultra_vague(_LV_PROMPT) is True
    assert prompt_looks_ultra_vague("请详细分析以下合同第3条……" * 5) is False
    kws = extract_topic_keywords(_TOPIC)
    assert kws  # 长中文句应切出可匹配片段
    assert any(len(k) >= 2 and k in _TOPIC for k in kws)
    assert motion_preserves_topic(_TOPIC, _TOPIC) is True
    assert motion_preserves_topic("无关天气话题", _TOPIC) is False
    assert motion_preserves_topic(
        "一审认定茉莉奶白四叶花卉图形不侵犯 LV 商标权应否维持",
        _LV_PROMPT,
    ) is True


def test_positive_sample_all_pass():
    report = evaluate_rings(_positive_bundle())
    assert report.all_pass, format_report(report)
    by = {r.ring: r for r in report.rings}
    assert by[1].status == "PASS"
    assert by[2].status == "PASS"
    assert by[3].status == "PASS"
    assert by[4].status == "PASS"
    assert by[5].status == "PASS"
    assert by[6].status == "PASS"
    assert by[6].checks["named_count"] >= 1
    assert by[6].checks["ledger_count"] >= 1
    assert report.metrics["debater_search_total"] == 1
    assert report.metrics["debater_budget_violations"] == {}
    assert report.metrics["research_file_read_hits"] >= 2
    assert report.metrics["dossier_index_files"] == 5
    assert report.metrics["debater_search_baseline_old"] == BASELINE_DEBATER_SEARCHES
    assert report.metrics["witness_named_count"] >= 1
    assert report.metrics["witness_ledger_count"] >= 1


def test_negative_sample_fails_expected_rings():
    report = evaluate_rings(_negative_bundle())
    assert report.all_pass is False
    by = {r.ring: r for r in report.rings}
    assert by[1].status == "FAIL"  # 超笼统无 ask
    assert by[2].status == "FAIL"  # 缺四透镜/文件/保真
    assert by[3].status == "FAIL"  # 无 resolved start_debate
    assert by[5].status == "FAIL"  # 无 debate/ 双产物
    assert by[6].status == "N/A"  # 无幕2 辩论


def test_mlr_debate_acts_vector_fails_stage_card_auth():
    """幕序列向量走 preview 授权、无推进卡 → 环3 FAIL；有透镜+辩论无证人 → 环6 FAIL。"""
    bundle = sse_events_to_bundle(
        _multi_agent_mlr_debate_acts(),
        user_prompt=_TOPIC,
        workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
    )
    report = evaluate_rings(bundle)
    by = {r.ring: r for r in report.rings}
    assert by[3].status == "FAIL"
    assert by[3].checks.get("authorized_by") == "preview"
    assert by[6].status == "FAIL"
    assert by[6].checks["named_count"] == 0


def test_witness_vector_ring6_pass():
    """证人 conformance 向量：环6 PASS（点名+台账）；环3 可能因授权源非 stage_card 而 FAIL。"""
    bundle = sse_events_to_bundle(
        _multi_agent_mlr_debate_witness(),
        user_prompt=_TOPIC,
        workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
    )
    report = evaluate_rings(bundle)
    by = {r.ring: r for r in report.rings}
    assert by[6].status == "PASS", format_report(report)
    assert by[6].checks["named_count"] >= 1
    assert by[6].checks["ledger_count"] >= 1
    assert any(k.startswith("witness:") for k in by[6].checks.get("ledger_side_keys") or [])


def test_ring6_fail_when_named_but_no_ledger():
    """点名有、台账无 → 环6 FAIL。"""
    events = []
    for ev in _enrich_stage_card_positive():
        if isinstance(ev, dict) and ev.get("type") == "debate_result":
            p = dict(ev["payload"])
            p["evidence_ledger"] = [
                x for x in (p.get("evidence_ledger") or []) if not str(x.get("side_key") or "").startswith("witness:")
            ]
            for rd in p.get("rounds") or []:
                if isinstance(rd, dict):
                    rd["evidence_ledger_delta"] = []
            events.append({"type": "debate_result", "payload": p})
        else:
            events.append(ev)
    report = evaluate_rings(
        sse_events_to_bundle(
            events,
            user_prompt=_TOPIC,
            workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
        )
    )
    assert report.rings[5].status == "FAIL"
    assert report.rings[5].checks["named_count"] >= 1
    assert report.rings[5].checks["ledger_count"] == 0


def test_ring6_na_when_roster_empty():
    """witnesses=[] 显式空 roster → 环6 N/A（探测无 session）。"""
    events = []
    for ev in _enrich_stage_card_positive():
        if isinstance(ev, dict) and ev.get("type") == "debate_result":
            p = dict(ev["payload"])
            p["witnesses"] = []
            p["witness_exam"] = []
            p["evidence_ledger"] = [
                x
                for x in (p.get("evidence_ledger") or [])
                if not str(x.get("side_key") or "").startswith("witness:")
            ]
            p["rounds"] = []
            events.append({"type": "debate_result", "payload": p})
        else:
            events.append(ev)
    report = evaluate_rings(
        sse_events_to_bundle(
            events,
            user_prompt=_TOPIC,
            workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
        )
    )
    assert report.rings[5].status == "N/A"
    assert report.all_pass  # N/A 不阻断


def test_stage_card_vector_partial_pass_ring3_structure():
    """stage_card 向量本身：环3 结构字段齐全；缺证人 → 环6 FAIL；缺案卷 → 环2/5 FAIL。"""
    bundle = sse_events_to_bundle(
        _multi_agent_stage_card_start_debate(),
        user_prompt=_TOPIC,
        workspace_files=[],
    )
    report = evaluate_rings(bundle)
    by = {r.ring: r for r in report.rings}
    assert by[3].checks["stage_card_required"] is True
    assert by[3].checks["stage_card_resolved_start_debate"] is True
    assert by[3].checks["authorized_by"] == "stage_card"
    # 无工作区文件 → 环2/5 FAIL；有透镜+辩论无证人 → 环6 FAIL
    assert by[2].status == "FAIL"
    assert by[5].status == "FAIL"
    assert by[6].status == "FAIL"


def test_ring1_na_when_prompt_clear():
    bundle = sse_events_to_bundle(
        _multi_agent_stage_card_start_debate(),
        user_prompt=(
            "请基于已有卷宗，就「品牌是否应立即终止争议代言联名」做多视角调研："
            "法律条款、合同违约金、舆情窗口与文化圈层冲突均需覆盖，输出命题卡。"
        ),
        workspace_files=_RESEARCH_FILES,
    )
    report = evaluate_rings(bundle)
    assert report.rings[0].status == "N/A"


def test_format_report_contains_table():
    text = format_report(evaluate_rings(_positive_bundle()), conversation_id="c1")
    assert "六环验收" in text
    assert "PASS" in text
    assert "量化指标" in text
    assert "证人点名" in text


def test_cost_metrics_when_turn_ids_present():
    """带 turn_id 的事件才能分幕费用；缺 turn_id 时进 gaps 而非硬造。"""
    tagged = []
    current = "m1"
    for ev in _multi_agent_stage_card_start_debate():
        if ev.type.value == "message_start":
            current = str(ev.payload.get("message_id") or current)
        tagged.append(
            {"type": ev.type.value, "payload": ev.payload, "turn_id": current}
        )
    bundle = sse_events_to_bundle(
        tagged,
        user_prompt=_TOPIC,
        workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
        message_costs={"m1": {"total_usd": 1.0}, "m2": {"total_usd": 2.0}},
    )
    report = evaluate_rings(bundle)
    assert report.metrics["cost_total"] == 3.0
    assert report.metrics["cost_act1"] == 1.0
    assert report.metrics["cost_act2"] == 2.0


def test_cost_gap_without_message_costs():
    report = evaluate_rings(
        sse_events_to_bundle(
            _multi_agent_stage_card_start_debate(),
            user_prompt=_TOPIC,
            workspace_files=[],
        )
    )
    assert any("费用" in g for g in report.gaps)
    assert report.metrics["cost_total"] is None


def test_search_budget_constant_aligned_with_mechanism():
    """环4 硬判据常数须与引擎侧有案卷辩手预算同源（机制对齐，2026-07-20 定案）。"""
    from agentcore.runtime.runs.retrieval_budget import (
        DEFAULT_RETRIEVAL_BUDGET_DEBATER_WITH_DOSSIER,
    )

    assert SEARCH_BUDGET_PER_RUN == DEFAULT_RETRIEVAL_BUDGET_DEBATER_WITH_DOSSIER
    assert SEARCH_BUDGET_PER_RUN < BASELINE_DEBATER_SEARCHES


def test_ring4_total_is_observation_only():
    """判据变更钉子：多辩手 run 各自守住单 run 预算时，总量再大也不判 FAIL。"""
    extra = []
    # 凑足总量 > 旧场级天花板 28（预算 4→2 后需更多 run：15×2=30）
    total_runs = max(10, (28 // SEARCH_BUDGET_PER_RUN) + 1)
    for i in range(total_runs):
        rid = f"debate_mod_sc_extra{i}_pro"  # 避开夹具已有的 r1_pro
        extra.append(run_started(rid, rid))
        for j in range(SEARCH_BUDGET_PER_RUN):
            extra.append(
                tool_use_start(f"s{i}_{j}", "web_search", {"query": "缺口"}, run_id=rid)
            )
    report = evaluate_rings(
        sse_events_to_bundle(
            _enrich_stage_card_positive() + extra,
            user_prompt=_TOPIC,
            workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
        )
    )
    by = {r.ring: r for r in report.rings}
    assert report.metrics["debater_search_total"] > 28
    assert report.metrics["debater_budget_violations"] == {}
    assert by[4].status == "PASS", format_report(report)


def test_ring4_fails_when_single_run_exceeds_budget():
    """任一辩手 run 成功完成的检索超机制预算 → 环4 FAIL 并点名（抓预算强制被绕过）。"""
    from agentcore.runtime.events import tool_use_end

    rid = "debate_mod_sc_r9_con"
    extra = [run_started(rid, rid)]
    for j in range(SEARCH_BUDGET_PER_RUN + 1):
        extra.append(
            tool_use_start(f"x{j}", "web_search", {"query": "重搜底料"}, run_id=rid)
        )
        extra.append(
            tool_use_end(f"x{j}", "web_search", success=True, output="ok", run_id=rid)
        )
    report = evaluate_rings(
        sse_events_to_bundle(
            _enrich_stage_card_positive() + extra,
            user_prompt=_TOPIC,
            workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
        )
    )
    by = {r.ring: r for r in report.rings}
    assert by[4].status == "FAIL"
    assert by[4].checks["budget_violations"] == {rid: SEARCH_BUDGET_PER_RUN + 1}


def test_ring4_rejected_attempts_do_not_count_as_violation():
    """引擎拒绝的检索发起（预算已尽/入参闸）不占槽：发起 6 成功 4 → 不判超支。

    钉住真跑形态：预算耗尽后模型多发起 2 次、被引擎回「预算已尽」拒绝——
    那是机制在工作，不是超支（成功完成口径 = 机制记账口径）。
    """
    from agentcore.runtime.events import tool_use_end

    rid = "debate_mod_sc_r9_con"
    extra = [run_started(rid, rid)]
    for j in range(SEARCH_BUDGET_PER_RUN + 2):
        ok = j < SEARCH_BUDGET_PER_RUN
        extra.append(
            tool_use_start(f"x{j}", "web_search", {"query": "缺口"}, run_id=rid)
        )
        extra.append(
            tool_use_end(
                f"x{j}",
                "web_search",
                success=ok,
                output="ok" if ok else "检索预算已尽",
                run_id=rid,
            )
        )
    report = evaluate_rings(
        sse_events_to_bundle(
            _enrich_stage_card_positive() + extra,
            user_prompt=_TOPIC,
            workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
        )
    )
    by = {r.ring: r for r in report.rings}
    assert by[4].status == "PASS", format_report(report)
    assert by[4].checks["budget_violations"] == {}
    # 发起口径仍如实观测（6 次），预算口径只记成功 4 次
    assert report.metrics["debater_search_by_run"][rid] == SEARCH_BUDGET_PER_RUN + 2
    assert (
        report.metrics["debater_search_charged_by_run"][rid] == SEARCH_BUDGET_PER_RUN
    )


def test_search_attribution_excludes_lens_and_witness():
    """环4 检索口径只计辩手：幕1 透镜本职检索与证人答问核实不得挤占辩手预算口径。"""
    events = _enrich_stage_card_positive() + [
        # 幕1 透镜检索（run_started 声明 stance 缺省 → 非辩手）
        run_started("del_x_lens_0", "del_x_lens_0"),
        tool_use_start("lw1", "web_search", {"query": "底料"}, run_id="del_x_lens_0"),
        tool_use_start("lw2", "web_search", {"query": "底料2"}, run_id="del_x_lens_0"),
        # 幕2 证人席位答问核实检索
        tool_use_start(
            "ww1",
            "web_search",
            {"query": "核实"},
            run_id="debate_mod_sc_r1_wit_del_x_lens_0",
        ),
    ]
    report = evaluate_rings(
        sse_events_to_bundle(
            events,
            user_prompt=_TOPIC,
            workspace_files=_RESEARCH_FILES + _DEBATE_FILES,
        )
    )
    m = report.metrics
    assert m["debater_search_total"] == 1  # 仅 pro 的 ws1
    assert m["witness_search_total"] == 1
    assert m["non_debater_search_total"] == 2
    assert "del_x_lens_0" not in m["debater_search_by_debater"]


def test_fixture_cli_ring6_pass():
    """--fixture 离线路径可验证环6（子进程跑 CLI，零 DB）。"""
    assert _FIXTURE_RING6.is_file(), f"missing fixture {_FIXTURE_RING6}"
    proc = subprocess.run(
        [
            sys.executable,
            str(_SERVER_ROOT / "scripts" / "mlr_golden_rings_check.py"),
            "--fixture",
            str(_FIXTURE_RING6),
            "--json",
        ],
        cwd=str(_SERVER_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    by = {r["ring"]: r for r in data["rings"]}
    assert by[6]["status"] == "PASS"
    assert data["all_pass"] is True
