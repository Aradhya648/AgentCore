"""Pin pedagogy-facing helpers in scripts/_mlr_two_act_verify.py (no live LLM).

``scripts/`` is not a package — load by file path like test_log_stats.
批 C：新链路 = ask_user → MLR → stage_card resolve start_debate（无 chip / 无口头同意）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "mlr_two_act_verify",
    Path(__file__).resolve().parents[1] / "scripts" / "_mlr_two_act_verify.py",
)
mlr = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(mlr)


def test_act1_prompt_is_ultra_vague_user_line():
    """幕1 输入应为题材+终局诉求的超笼统句，不写硬性编排约束。"""
    prompt = mlr.ACT1_PROMPT
    assert "模拟法庭" in prompt
    assert "茉莉奶白" in prompt or "LV" in prompt
    assert "硬性要求" not in prompt
    assert "playbook=multi_lens_research" not in prompt
    assert "motion_card" not in prompt


def test_resume_body_confirms_ask_user_start():
    pause = {
        "type": "ask_user_required",
        "payload": {
            "checkpoint_id": "ck1",
            "questions": [
                {
                    "prompt": "是否启动多视角深度调研？",
                    "options": ["确认启动", "暂不启动"],
                    "multiple": False,
                }
            ],
        },
    }
    body = mlr._resume_body_for_pause(pause)
    assert body["decision"] == "continue"
    assert "确认启动" in body["note"]
    assert body["selected"] == ["确认启动"]


def test_resume_body_confirms_checkpoint_required_kickoff():
    """wire 上 ask_user 冷挂起发 checkpoint_required（含 questions options）。"""
    pause = {
        "type": "checkpoint_required",
        "payload": {
            "checkpoint_id": "ck-kick",
            "question": "即将启动多维深度取证",
            "questions": [
                {
                    "prompt": "确认启动四路深度调研？",
                    "options": [
                        {"label": "启动四路调研，按标准流程走", "recommended": True},
                        {"label": "直接跳过调研，立即开庭模拟法庭"},
                    ],
                    "multiple": False,
                }
            ],
            "intent": "kickoff",
        },
    }
    body = mlr._resume_body_for_pause(pause)
    assert body["decision"] == "continue"
    assert "确认启动" in body["note"]
    assert body["selected"] == ["启动四路调研，按标准流程走"]


def test_resume_body_plain_continue_for_team_preview():
    pause = {"type": "team_preview_required", "payload": {"checkpoint_id": "ck2"}}
    body = mlr._resume_body_for_pause(pause)
    assert body == {"decision": "continue", "note": ""}


def test_pick_ask_affirmative_falls_back_to_first_option():
    selected = mlr._pick_ask_affirmative_selected(
        {"questions": [{"options": ["方案甲", "方案乙"], "multiple": False}]}
    )
    assert selected == ["方案甲"]


def test_motion_preserves_case_object_accepts_case_level_motion():
    ok = "一审认定茉莉奶白四叶花卉图形不侵犯 LV 商标权应否维持"
    assert mlr._motion_preserves_case_object(ok) is True


def test_motion_preserves_case_object_rejects_pure_institutional():
    bad = "商标法应否为公共文化符号设跨类保护例外"
    assert mlr._motion_preserves_case_object(bad) is False


def test_analyze_act1_flags_motion_fidelity_failure():
    events = [
        {
            "type": "tool_use_start",
            "t_ms": 1,
            "payload": {
                "run_id": "synth_0",
                "name": "handoff",
                "arguments": {
                    "motion_card": {
                        "motion": "商标法应否为公共文化符号设跨类保护例外",
                        "sides": [],
                    }
                },
            },
        }
    ]
    analysis = mlr._analyze_act1(events)
    assert analysis["synth_handoff_has_motion_card"] is True
    assert analysis["motion_fidelity_ok"] is False
    assert analysis["motion_texts"]


def test_extract_stage_card_from_events():
    events = [
        {
            "type": "stage_card_required",
            "t_ms": 10,
            "payload": {
                "stage_card_id": "sc-1",
                "motion": "一审认定茉莉奶白四叶花卉图形不侵犯 LV 商标权应否维持",
                "sides": [{"key": "a", "name": "正方", "stance": "应维持"}],
                "form": "debate",
            },
        }
    ]
    card = mlr._extract_stage_card(events)
    assert card is not None
    assert card["stage_card_id"] == "sc-1"
    assert "茉莉奶白" in card["motion"]


def test_analyze_act1_detects_stage_card_and_ask_user():
    events = [
        {
            "type": "tool_use_start",
            "t_ms": 0,
            "payload": {"name": "ask_user"},
        },
        {"type": "checkpoint_required", "t_ms": 1, "payload": {"checkpoint_id": "ck"}},
        {
            "type": "_meta",
            "t_ms": 2,
            "payload": {"ask_user_resumes": 1, "resume_rounds": 1},
        },
        {
            "type": "stage_card_required",
            "t_ms": 3,
            "payload": {
                "stage_card_id": "sc-2",
                "motion": "一审认定茉莉奶白四叶花卉图形不侵犯 LV 商标权应否维持",
                "sides": [],
                "form": "debate",
            },
        },
    ]
    analysis = mlr._analyze_act1(events)
    assert analysis["stage_card_required"] is True
    assert analysis["ask_user_required_count"] == 1  # checkpoint_required counted
    assert analysis["ask_user_tool"] is True
    assert analysis["ask_user_resumes"] == 1
    assert analysis["motion_fidelity_ok"] is True


def test_analyze_act2_host_growth_and_searches():
    events = [
        {
            "type": "graph_append",
            "t_ms": 1,
            "payload": {
                "execution_id": "exec-host",
                "host_message_id": "m1",
                "append_message_id": "m2",
                "added_count": 1,
                "act_id": "act-2",
                "act_kind": "debate",
                "authorized_by": "stage_card",
            },
        },
        {
            "type": "run_plan",
            "t_ms": 2,
            "payload": {
                "execution_id": "exec-host",
                "plan_type": "debate",
                "task_summary": "辩论",
                "agents": [],
                "runs": [],
                "host_message_id": "m1",
                "act": {
                    "act_id": "act-2",
                    "kind": "debate",
                    "authorized_by": "stage_card",
                    "anchor_run_id": "synthesizer_abc",
                },
            },
        },
        {
            "type": "tool_call_started",
            "t_ms": 3,
            "payload": {"name": "web_search", "run_id": "debater_a"},
        },
        {
            "type": "tool_call_started",
            "t_ms": 4,
            "payload": {"name": "read_url", "run_id": "debater_b"},
        },
        {
            "type": "content_delta",
            "t_ms": 5,
            "payload": {"delta": "依据 research/法律透镜报告.md 与案卷…法律/商业/公关/制度"},
        },
    ]
    analysis = mlr._analyze_act2(events)
    assert analysis["authorized_by_stage_card"] is True
    assert analysis["act_id"] == "act-2"
    assert analysis["anchor_is_synthesizer"] is True
    assert analysis["debater_searches"]["total"] == 2
    assert analysis["cites_research_files"] is True
    assert analysis["four_dim_ok"] is True


def test_count_debater_searches_ignores_file_tools():
    events = [
        {"type": "tool_call_started", "t_ms": 1, "payload": {"name": "file_read"}},
        {"type": "tool_call_started", "t_ms": 2, "payload": {"name": "web_search"}},
        {"type": "tool_call_started", "t_ms": 3, "payload": {"name": "grep"}},
    ]
    counts = mlr._count_debater_searches(events)
    assert counts["total"] == 1
    assert counts["by_tool"] == {"web_search": 1}
    assert counts["baseline"] == 56


def test_expected_research_files_are_five():
    assert len(mlr._EXPECTED_RESEARCH_FILES) == 5
    assert "research/汇总与命题卡.md" in mlr._EXPECTED_RESEARCH_FILES


def test_ring_report_all_pass():
    report = mlr._ring_report(
        ring1={"pass": True, "detail": "ok"},
        ring2={"pass": True, "detail": "ok"},
        ring3={"pass": True, "detail": "ok"},
        ring4={"pass": True, "detail": "ok"},
        ring5={"pass": True, "detail": "ok"},
    )
    assert report["all_pass"] is True
    report_fail = mlr._ring_report(
        ring1={"pass": True, "detail": "ok"},
        ring2={"pass": False, "detail": "missing"},
        ring3={"pass": True, "detail": "ok"},
        ring4={"pass": True, "detail": "ok"},
        ring5={"pass": True, "detail": "ok"},
    )
    assert report_fail["all_pass"] is False
