"""RunSession JSON (de)serialization (P3 跨进程落盘).

Pins that a transcript — including a worker's tool-call turns and tool-result
messages — and a RunSpec with nested RunPolicy / RunContract round-trip losslessly,
so a session loaded from the DB replays the exact context for ``continue_run``.
"""

from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.journal import completed_from_journal
from agentcore.runtime.runs import RunPlan, RunSession, RunSpec
from agentcore.runtime.runs.serialize import (
    escalations_from_transcript,
    files_touched_from_transcript,
    plan_from_json,
    plan_to_json,
    run_final_fact,
    session_from_row,
    session_to_row,
    spec_from_json,
    spec_to_json,
    state_from_json,
    state_to_json,
    transcript_from_json,
    transcript_to_json,
)
from agentcore.runtime.runs.types import Deliverable, RunKind, RunPhase, RunPolicy, RunState


def _assistant_call(call_id: str, name: str, arguments: str) -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(id=call_id, function=ToolCallFunction(name=name, arguments=arguments))
        ],
    )


def test_files_touched_from_transcript_collects_produced_paths_in_order():
    transcript = [
        LLMMessage(role="user", content="建站"),
        _assistant_call("c1", "file_write", '{"path": "index.html", "content": "<html>"}'),
        LLMMessage(role="tool", content="已写入", tool_call_id="c1"),
        _assistant_call("c2", "web_search", '{"query": "x"}'),  # non-mutating → ignored
        _assistant_call(
            "c3", "str_replace", '{"path": "index.html", "old_string": "a", "new_string": "b"}'
        ),
        LLMMessage(role="tool", content="已替换", tool_call_id="c3"),
        _assistant_call("c4", "file_move", '{"source": "a.txt", "destination": "docs/b.txt"}'),
        LLMMessage(role="tool", content="已移动", tool_call_id="c4"),
        LLMMessage(role="assistant", content="完成"),
    ]
    # index.html deduped (write + edit), file_move records its destination, web_search dropped.
    assert files_touched_from_transcript(transcript) == ["index.html", "docs/b.txt"]


def test_files_touched_from_transcript_collects_file_append():
    transcript = [
        _assistant_call("c1", "file_write", '{"path": "doc.md", "content": "# Title"}'),
        _tool_result("c1", "已写入"),
        _assistant_call("c2", "file_append", '{"path": "doc.md", "content": "\\n## Section"}'),
        _tool_result("c2", "已追加"),
    ]
    assert files_touched_from_transcript(transcript) == ["doc.md"]


def test_files_touched_from_transcript_skips_malformed_and_pathless():
    transcript = [
        _assistant_call("c1", "file_write", "not valid json"),
        _tool_result("c1", "已写入"),
        _assistant_call("c2", "file_read", '{"path": "x"}'),  # read is not a product
        _tool_result("c2", "内容"),
        _assistant_call("c3", "file_write", '{"content": "no path here"}'),
        _tool_result("c3", "已写入"),
    ]
    assert files_touched_from_transcript(transcript) == []


def test_files_touched_skips_failed_or_denied_file_write():
    # 执行成功口径: allowlist / 审批 / 熔断拒绝与执行失败均带 tool_failed 尾注 → 不记账；
    # 无 tool result 的裸调用也不记账（意图不等于落盘）。
    from agentcore.runtime.engine.tool_exec import TOOL_FAILED_MARKER, with_tool_failed_marker
    from agentcore.runtime.runs.serialize import _TOOL_FAILED_MARKER, _tool_result_failed

    transcript = [
        _assistant_call("c1", "file_write", '{"path": "ghost.md", "content": "x"}'),
        _tool_result("c1", with_tool_failed_marker("工具不在允许列表中，未执行。")),
        _assistant_call("c2", "file_write", '{"path": "ok.md", "content": "y"}'),
        _tool_result("c2", "已写入 3 字节到 ok.md"),
        _assistant_call("c3", "file_move", '{"source": "a", "destination": "b/out.txt"}'),
        _tool_result("c3", with_tool_failed_marker("未获用户授权，该操作未执行。")),
        _assistant_call("c4", "file_write", '{"path": "bare.md", "content": "z"}'),
        # no tool result → not counted
    ]
    assert files_touched_from_transcript(transcript) == ["ok.md"]
    # Round-trip: producer ↔ consumer marker format locked.
    assert TOOL_FAILED_MARKER == _TOOL_FAILED_MARKER == "<!--agentcore:tool_failed-->"
    assert _tool_result_failed(with_tool_failed_marker("err")) is True
    assert _tool_result_failed("已写入") is False


def _tool_result(call_id: str, content: str) -> LLMMessage:
    return LLMMessage(role="tool", content=content, tool_call_id=call_id)


def test_files_touched_harvests_code_execute_write_back_marker():
    # 结构化写回通道: a code_execute RESULT's machine marker (sandbox copy-out paths)
    # counts toward files_touched — a product landed by an executed script is visible to
    # requires_files / the manifest WITHOUT parsing the fragile「已写回工作区」prose. This
    # also pins the producer↔consumer format (render_written_files_marker is the producer).
    from agentcore.tools.builtin.code_execute import render_written_files_marker

    transcript = [
        _assistant_call("c1", "code_execute", '{"code": "make()", "language": "python"}'),
        _tool_result(
            "c1",
            "stdout:\ndone\n\n已写回工作区：out/report.md\n"
            + render_written_files_marker(["out/report.md"]),
        ),
    ]
    assert files_touched_from_transcript(transcript) == ["out/report.md"]


def test_files_touched_merges_code_execute_and_file_tools_first_seen_order():
    from agentcore.tools.builtin.code_execute import render_written_files_marker

    transcript = [
        _assistant_call("c1", "file_write", '{"path": "a.txt", "content": "x"}'),
        _tool_result("c1", "已写入"),
        _assistant_call("c2", "code_execute", '{"code": "gen()"}'),
        _tool_result("c2", render_written_files_marker(["b.csv", "a.txt"])),
    ]
    # First-seen order across both channels; a.txt landed by both → listed once.
    assert files_touched_from_transcript(transcript) == ["a.txt", "b.csv"]


def test_files_touched_collects_multiple_code_execute_calls():
    from agentcore.tools.builtin.code_execute import render_written_files_marker

    transcript = [
        _assistant_call("c1", "code_execute", "{}"),
        _tool_result("c1", render_written_files_marker(["one.md"])),
        _assistant_call("c2", "code_execute", "{}"),
        _tool_result("c2", render_written_files_marker(["two.md", "one.md"])),
    ]
    assert files_touched_from_transcript(transcript) == ["one.md", "two.md"]


def test_files_touched_skips_malformed_or_uncorrelated_write_back_marker():
    # A truncated / malformed marker JSON is skipped (best-effort — file-tool intent
    # still covers file_write); a marker sitting in a NON-code_execute result (e.g. a
    # file_read echoing one back) is never counted — correlation is by tool_call_id.
    transcript = [
        _assistant_call("c1", "code_execute", "{}"),
        _tool_result("c1", '<!--agentcore:written_files:["broken'),  # truncated JSON
        _assistant_call("c2", "file_read", '{"path": "notes.md"}'),
        _tool_result("c2", '<!--agentcore:written_files:["ghost.md"]-->'),  # not code_execute
    ]
    assert files_touched_from_transcript(transcript) == []


def test_state_json_round_trips_files_touched():
    state = RunState(phase=RunPhase.COMPLETED, content="x", files_touched=["a.html", "b.css"])
    restored = state_from_json(state_to_json(state))
    assert restored.files_touched == ["a.html", "b.css"]


def test_state_json_round_trips_debrief():
    # 完工交接简报: a seed/resume must carry the worker's harvested debrief so downstream
    # injection / CEO synthesis on a resumed turn read the same author 结论 / 建议下一步.
    state = RunState(
        phase=RunPhase.COMPLETED,
        content="x",
        debrief={"summary": "做完了甲", "next_steps": "接着做乙"},
    )
    restored = state_from_json(state_to_json(state))
    assert restored.debrief == {"summary": "做完了甲", "next_steps": "接着做乙"}


def test_state_json_debrief_defaults_none():
    restored = state_from_json(state_to_json(RunState(phase=RunPhase.COMPLETED, content="x")))
    assert restored.debrief is None


def test_state_json_round_trips_error_retryable():
    # 确定性失败区分 (BL-6): a deterministic failure's non-retryable verdict must survive the
    # seed / journal round-trip so a resume / retry-failed rebuild + the audit trail keep it.
    state = RunState(phase=RunPhase.FAILED, error="prompt too long", error_retryable=False)
    restored = state_from_json(state_to_json(state))
    assert restored.error_retryable is False


def test_state_json_error_retryable_defaults_true():
    # A COMPLETED state (and any older frame missing the key) defaults to retryable=True,
    # so ordinary retry behaviour is unchanged for pre-BL-6 rows.
    restored = state_from_json(state_to_json(RunState(phase=RunPhase.COMPLETED, content="x")))
    assert restored.error_retryable is True
    assert state_from_json({"phase": "failed", "error": "x"}).error_retryable is True


def test_escalations_from_transcript_collects_in_call_order():
    transcript = [
        LLMMessage(role="user", content="做事"),
        _assistant_call(
            "c1",
            "escalate",
            '{"question": "Postgres 还是 MySQL?", "assumption": "暂用 PG", "blocking": true}',
        ),
        LLMMessage(role="tool", content="已记录", tool_call_id="c1"),
        _assistant_call("c2", "web_search", '{"query": "x"}'),  # not an escalation
        _assistant_call("c3", "escalate", '{"question": "目标受众是谁?"}'),
        LLMMessage(role="assistant", content="完成"),
    ]
    out = escalations_from_transcript(transcript)
    assert out == [
        {
            "question": "Postgres 还是 MySQL?",
            "assumption": "暂用 PG",
            "blocking": True,
            "kind": "normal",
            "status": "raised",
            "answer": None,
        },
        {
            "question": "目标受众是谁?",
            "assumption": "",
            "blocking": False,
            "kind": "normal",
            "status": "raised",
            "answer": None,
        },
    ]


def test_escalations_from_transcript_marks_scope_and_dep_kinds():
    # 受监督的波循环: escalate(kind="scope") 职责偏离 and escalate(kind="dep") 依赖缺口
    # (§2.4 卡在缺输入 X) are BOTH harvested with their kind (the WaveScheduler consumes both
    # at the reactive boundary); an unknown kind degrades to "normal", a plain escalate defaults.
    transcript = [
        _assistant_call(
            "c1",
            "escalate",
            '{"question": "真问题是X不是Y", "assumption": "暂按X", "kind": "scope"}',
        ),
        _assistant_call(
            "c2",
            "escalate",
            '{"question": "缺错误返回结构才能写测试", "assumption": "暂按 {code,msg}", "kind": "dep"}',
        ),
        _assistant_call("c3", "escalate", '{"question": "未知档", "kind": "weird"}'),
        _assistant_call("c4", "escalate", '{"question": "普通问题"}'),
    ]
    out = escalations_from_transcript(transcript)
    assert [e["kind"] for e in out] == ["scope", "dep", "normal", "normal"]
    assert out[0]["question"] == "真问题是X不是Y"
    assert out[1]["question"] == "缺错误返回结构才能写测试"


def test_escalations_from_transcript_skips_malformed_and_empty_question():
    transcript = [
        _assistant_call("c1", "escalate", "not valid json"),
        _assistant_call("c2", "escalate", '{"question": "   "}'),  # empty after strip
        _assistant_call("c3", "escalate", '{"assumption": "no question key"}'),
    ]
    assert escalations_from_transcript(transcript) == []


def test_state_json_round_trips_escalations():
    state = RunState(
        phase=RunPhase.COMPLETED,
        content="x",
        escalations=[{"question": "q1", "assumption": "a1", "blocking": True}],
    )
    restored = state_from_json(state_to_json(state))
    assert restored.escalations == [{"question": "q1", "assumption": "a1", "blocking": True}]


def test_state_json_round_trips_scope_consumed_escalation():
    # 受监督的波循环 P5: a scope escalation's ``kind`` AND the scheduler-set ``consumed``
    # flag must survive the seed round-trip, so a re-drive does not re-fire a SCOPE boundary
    # already handled (state_from_json/to_json copy the dicts whole — every key rides).
    state = RunState(
        phase=RunPhase.COMPLETED,
        content="A 的产出",
        escalations=[{"question": "真问题是X", "kind": "scope", "consumed": True}],
    )
    restored = state_from_json(state_to_json(state))
    assert restored.escalations == [{"question": "真问题是X", "kind": "scope", "consumed": True}]


def test_run_final_fact_completed_from_journal_preserves_scope_consumed():
    # 单一事实源 (P5 持久化): a worker's terminal RunState journaled as a message_final fact
    # (run_final_fact) must rebuild — via completed_from_journal — with its scope escalation
    # AND consumed flag intact, the durable twin of the in-memory seed (drive.py re-journals
    # the consumed state at a SCOPE yield so this projection carries it).
    state = RunState(
        phase=RunPhase.COMPLETED,
        content="A 的产出",
        escalations=[{"question": "真问题是X", "kind": "scope", "consumed": True}],
    )
    fact = run_final_fact("a", state)
    entry = {"kind": fact.kind, "payload": fact.payload}
    rebuilt = completed_from_journal([entry])
    assert set(rebuilt) == {"a"}
    assert rebuilt["a"].escalations == [
        {"question": "真问题是X", "kind": "scope", "consumed": True}
    ]


def test_transcript_round_trips_with_tool_calls_and_tool_results():
    transcript = [
        LLMMessage(role="system", content="sys"),
        LLMMessage(role="user", content="做A"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function=ToolCallFunction(name="web_search", arguments='{"q":"x"}'),
                )
            ],
        ),
        LLMMessage(role="tool", content="结果…", tool_call_id="call_1"),
        LLMMessage(role="assistant", content="最终产出", reasoning_content="想了想"),
    ]
    restored = transcript_from_json(transcript_to_json(transcript))
    assert len(restored) == 5
    # tool-call turn preserved (content None, one ToolCall with function fields)
    tc_msg = restored[2]
    assert tc_msg.role == "assistant"
    assert tc_msg.content is None
    assert tc_msg.tool_calls[0].id == "call_1"
    assert tc_msg.tool_calls[0].function.name == "web_search"
    assert tc_msg.tool_calls[0].function.arguments == '{"q":"x"}'
    # tool-result turn preserved (role + tool_call_id linkage)
    assert restored[3].role == "tool"
    assert restored[3].tool_call_id == "call_1"
    # final answer + reasoning preserved
    assert restored[4].content == "最终产出"
    assert restored[4].reasoning_content == "想了想"


def test_spec_round_trips_with_nested_policy_and_deliverable():
    spec = RunSpec(
        run_id="del_abc_1",
        task="做A",
        kind=RunKind.AGENT,
        role="研究员",
        tools=["web_search", "read_url"],
        deliverable=Deliverable(must_contain=["风险"], min_length=100, strict=True),
        policy=RunPolicy(result_handling="summarize"),
    )
    restored = spec_from_json(spec_to_json(spec))
    assert restored.run_id == "del_abc_1"
    assert restored.role == "研究员"
    assert restored.tools == ["web_search", "read_url"]
    # kind coerced back to the enum
    assert restored.kind is RunKind.AGENT
    # nested policy is a real RunPolicy, and its deliverable a real Deliverable — so
    # continue_run's ``spec.deliverable`` keeps working after a DB round-trip.
    assert isinstance(restored.policy, RunPolicy)
    assert restored.policy.result_handling == "summarize"
    assert isinstance(restored.deliverable, Deliverable)
    assert restored.deliverable.must_contain == ["风险"]
    assert restored.deliverable.strict is True


def test_spec_without_deliverable_round_trips_to_none():
    spec = RunSpec(run_id="r1", task="t", policy=RunPolicy())
    restored = spec_from_json(spec_to_json(spec))
    assert restored.deliverable is None


def test_spec_unknown_persisted_keys_are_ignored():
    raw = {
        "run_id": "r1",
        "task": "t",
        "policy": {},
        "obsolete_field": "ignored",
    }
    restored = spec_from_json(raw)
    assert restored.run_id == "r1"
    assert restored.deliverable is None


def test_plan_json_round_trips_late_bound_placeholder_node():
    # 受监督的波循环 P5 (partial spec 往返): a bind_after_deps node carries a PLACEHOLDER spec
    # (its real role/task land at the BIND boundary via replan). The plan must serialize +
    # rebuild that partial node faithfully — bind_after_deps preserved, placeholders intact,
    # deps wired — so a paused supervised plan rebuilt from its plan_snapshot still knows the
    # node is待定稿 and never dispatches it unbound.
    plan = RunPlan(
        nodes=[
            RunSpec(run_id="a", task="调研", role="研究员"),
            RunSpec(
                run_id="b",
                task="占位",
                role="待定",
                depends_on=["a"],
                bind_after_deps=True,
            ),
        ]
    )
    restored = plan_from_json(plan_to_json(plan))
    a, b = restored.nodes
    assert (a.run_id, a.bind_after_deps) == ("a", False)
    assert b.run_id == "b"
    assert b.bind_after_deps is True  # the late-bind marker survives → still待定稿
    assert (b.role, b.task) == ("待定", "占位")  # placeholders intact
    assert b.depends_on == ["a"]


def test_spec_from_json_tolerates_unknown_and_missing_keys():
    # A row written by a different build (extra key) / missing an optional must still
    # load — _filtered drops unknowns, dataclass defaults fill the gaps.
    raw = {"run_id": "r1", "task": "t", "surprise_field": 1, "policy": {"ghost": 2}}
    spec = spec_from_json(raw)
    assert spec.run_id == "r1"
    assert spec.task == "t"
    assert isinstance(spec.policy, RunPolicy)


def test_session_row_round_trip():
    spec = RunSpec(run_id="del_x_1", task="t", role="A", policy=RunPolicy())
    session = RunSession(
        run_id="del_x_1",
        spec=spec,
        transcript=[LLMMessage(role="assistant", content="v1")],
        content="v1",
        recall_count=2,
    )
    row = session_to_row(session)
    assert row["run_id"] == "del_x_1"
    assert row["recall_count"] == 2
    assert row["content"] == "v1"
    assert isinstance(row["transcript"], list)
    assert isinstance(row["spec"], dict)

    # session_from_row reads attribute access (like the ORM row), so wrap in a shim.
    class _Row:
        run_id = row["run_id"]
        spec = row["spec"]
        transcript = row["transcript"]
        content = row["content"]
        recall_count = row["recall_count"]

    back = session_from_row(_Row())
    assert back.run_id == "del_x_1"
    assert back.recall_count == 2
    assert back.content == "v1"
    assert back.transcript[0].content == "v1"
    assert back.spec.role == "A"
