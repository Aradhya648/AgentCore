"""Basic delegate execute, validation, events, and schema tests."""

import agentcore.tools.builtin.delegate.tool as delegate_tool_mod
from agentcore.core.types import ToolEffect
from agentcore.llm.provider.protocol import TokenUsage
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.runs import BoundaryReason
from tests.conftest import LogSpy
from tests.delegate.conftest import LATE_BIND_DAG, Provider, _upstream_body, ctx, tool


async def test_parallel_delegate_returns_products_non_terminal():
    """经典阻塞路径：coordinate=false 时多 worker 等全队完成再返回产物。"""
    t = tool(Provider(["AOUT", "BOUT"]))
    result = await t.execute(
        {
            "tasks": [{"role": "研究员", "task": "做A"}, {"role": "写手", "task": "做B"}],
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True
    assert result.is_terminal is False
    assert "AOUT" in result.output
    assert "BOUT" in result.output
    assert "研究员" in result.output
    assert "写手" in result.output
    usage_keys = {
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cache_hit_tokens",
        "cache_miss_tokens",
    }
    assert usage_keys <= set(result.metadata)
    assert result.metadata.get("batch_nodes") == 2
    assert result.metadata.get("batch_has_deps") is False


async def test_dag_delegate_completes_with_both_products():
    tasks = [
        {"id": "s1", "role": "研究员", "task": "调研"},
        {"id": "s2", "role": "写手", "task": "撰写", "depends_on": ["s1"]},
    ]
    t = tool(Provider([_upstream_body("UPSTREAM"), _upstream_body("FINAL")]))
    result = await t.execute({"tasks": tasks, "coordinate": False}, ctx())
    assert result.success is True
    assert result.is_terminal is False
    assert "UPSTREAM" in result.output
    assert "FINAL" in result.output


async def test_finalize_single_worker_surfaces_directly_as_terminal():
    usage = TokenUsage(
        input_tokens=10,
        output_tokens=5,
        reasoning_tokens=0,
        cache_hit_tokens=6,
        cache_miss_tokens=4,
    )
    sink = EventSink()
    direct = _upstream_body("DIRECT")
    t = tool(Provider(["DIRECT"], usage=usage), sink=sink)
    result = await t.execute(
        {"tasks": [{"role": "工程师", "task": "建文件"}], "finalize": True}, ctx()
    )
    assert result.success is True
    assert result.is_terminal is True
    assert result.effect is ToolEffect.HANDOFF
    assert result.final_text == direct
    assert t.usage["input"] == 10
    assert "input_tokens" not in result.metadata
    sink.close()
    deltas = [e.payload["delta"] async for e in sink if e.type == EventType.CONTENT_DELTA]
    assert deltas == [direct]


async def test_finalize_ignored_for_multi_worker_batch():
    t = tool(Provider(["A", "B"]))
    result = await t.execute(
        {
            "tasks": [{"role": "A", "task": "a"}, {"role": "B", "task": "b"}],
            "finalize": True,
        },
        ctx(),
    )
    assert result.is_terminal is False
    assert "A" in result.output and "B" in result.output


async def test_finalize_falls_back_to_synthesis_when_worker_fails():
    t = tool(Provider(["X"]))
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "A",
                    "task": "a",
                    "deliverable": {"min_length": 100, "strict": True},
                }
            ],
            "finalize": True,
        },
        ctx(),
    )
    assert result.is_terminal is False


def test_should_auto_light_delegate():
    assert delegate_tool_mod._should_auto_light_delegate(
        [{"role": "工程师", "task": "做A"}]
    )
    assert not delegate_tool_mod._should_auto_light_delegate(
        [{"role": "A", "task": "a"}, {"role": "B", "task": "b"}]
    )
    assert not delegate_tool_mod._should_auto_light_delegate(
        [{"role": "A", "task": "a", "depends_on": ["x"]}]
    )
    assert not delegate_tool_mod._should_auto_light_delegate(
        [{"role": "A", "task": "a", "checkpoint_after": True}]
    )
    assert not delegate_tool_mod._should_auto_light_delegate(
        [{"role": "A", "task": "a", "bind_after_deps": True}]
    )
    # 深度交付与编排结构正交：单 worker 无波边界也不 auto-light
    assert not delegate_tool_mod._should_auto_light_delegate(
        [
            {
                "role": "工程师",
                "task": "写代码落盘",
                "deliverable": {"form": "files", "artifacts": ["app.py"]},
            }
        ]
    )


async def test_single_worker_auto_infers_light_complexity_hint(monkeypatch):
    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    t = tool(Provider(["OUT"]))
    await t.execute({"tasks": [{"role": "工程师", "task": "做A"}]}, ctx())
    assert spy.get("delegate.started")["complexity_hint"] == "light"


async def test_single_worker_deep_deliverable_skips_auto_light(monkeypatch):
    """单 worker 无波边界，但 deep deliverable 时不推断 light，保持 standard。"""
    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    t = tool(Provider(["OUT"]))
    await t.execute(
        {
            "tasks": [
                {
                    "role": "工程师",
                    "task": "实现功能并落盘",
                    "deliverable": {"form": "files", "artifacts": ["src/main.py"]},
                }
            ],
        },
        ctx(),
    )
    assert spy.get("delegate.started")["complexity_hint"] == "standard"
    assert not any(name == "delegate.complexity_hint_inferred" for name, _ in spy.events)


async def test_explicit_light_with_file_deliverable_kept_for_repair(monkeypatch):
    """显式 light + requires_files/artifacts → 保留 light（修码快修）；缩 max_rounds。"""
    import agentcore.runtime.runs as runs_mod

    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    captured: dict = {}
    real_build = runs_mod.build_run_plan

    def _capture_build(*args, **kwargs):
        plan, errors = real_build(*args, **kwargs)
        captured["complexity_hint"] = kwargs.get("complexity_hint")
        captured["max_rounds"] = plan.nodes[0].max_rounds if plan.nodes else None
        return plan, errors

    monkeypatch.setattr(runs_mod, "build_run_plan", _capture_build)
    t = tool(Provider(["OUT"]))
    await t.execute(
        {
            "tasks": [
                {
                    "role": "工程师",
                    "task": "修缺 export 并落盘",
                    "deliverable": {"form": "files", "artifacts": ["app.py"]},
                }
            ],
            "complexity_hint": "light",
        },
        ctx(),
    )
    assert spy.get("delegate.started")["complexity_hint"] == "light"
    assert not any(name == "delegate.complexity_hint_ignored" for name, _ in spy.events)
    assert captured["complexity_hint"] == "light"
    assert captured["max_rounds"] == 6


async def test_explicit_light_with_long_form_ignored(monkeypatch):
    """显式 light + 成篇长文仍忽略 → standard。"""
    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    t = tool(Provider(["OUT"]))
    await t.execute(
        {
            "tasks": [
                {
                    "role": "写手",
                    "task": "写长报告",
                    "deliverable": {"min_length": 3000, "name": "报告"},
                }
            ],
            "complexity_hint": "light",
        },
        ctx(),
    )
    assert spy.get("delegate.started")["complexity_hint"] == "standard"
    assert spy.get("delegate.complexity_hint_ignored")["reason"] == "long_form_deliverable"


async def test_multi_worker_keeps_standard_complexity_hint(monkeypatch):
    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    t = tool(Provider(["AOUT", "BOUT"]))
    await t.execute(
        {"tasks": [{"role": "研究员", "task": "做A"}, {"role": "写手", "task": "做B"}]},
        ctx(),
    )
    assert spy.get("delegate.started")["complexity_hint"] == "standard"


async def test_explicit_standard_complexity_hint_not_overridden(monkeypatch):
    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    t = tool(Provider(["OUT"]))
    await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "做A"}],
            "complexity_hint": "standard",
        },
        ctx(),
    )
    assert spy.get("delegate.started")["complexity_hint"] == "standard"


async def test_single_worker_with_checkpoint_keeps_standard_complexity_hint(monkeypatch):
    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    t = tool(Provider(["OUT"]))
    await t.execute(
        {
            "tasks": [
                {"role": "工程师", "task": "做A", "checkpoint_after": True},
            ],
        },
        ctx(),
    )
    assert spy.get("delegate.started")["complexity_hint"] == "standard"


async def test_explicit_light_with_dag_features_ignored(monkeypatch):
    """显式 light + depends_on/bind_after_deps 时忽略 light，保留波边界让出。"""
    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    provider = Provider([_upstream_body("AOUT"), _upstream_body("BOUT")])
    t = tool(provider)
    first = await t.execute(
        {
            "tasks": LATE_BIND_DAG,
            "complexity_hint": "light",
            "coordinate": False,
        },
        ctx(),
    )
    assert spy.get("delegate.started")["complexity_hint"] == "standard"
    assert first.success is True
    assert "计划已让出" in first.output
    assert "AOUT" in first.output
    assert "BOUT" not in first.output
    assert t._supervised is not None
    assert t._supervised.reason is BoundaryReason.BIND


async def test_multi_worker_default_coordination_none_skips_wall(monkeypatch):
    """多节点缺省 coordination=none：不建墙、不授便签三件套、无 team_note_posted。"""
    from agentcore.runtime.events import EventType
    from agentcore.runtime.runs.types import RunPhase, RunState

    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    captured: dict = {}

    async def _exec(spec, completed):  # noqa: ANN001
        return RunState(phase=RunPhase.COMPLETED, content=f"{spec.role}_OUT")

    def _capture_build(**kwargs):  # noqa: ANN003
        captured["collaboration"] = kwargs.get("collaboration")
        captured["note_wall"] = kwargs.get("note_wall")
        return _exec

    monkeypatch.setattr("agentcore.runtime.runs.build_agent_executor", _capture_build)
    sink = EventSink()
    t = tool(Provider([]), sink=sink)
    result = await t.execute(
        {
            "tasks": [{"role": "A", "task": "a"}, {"role": "B", "task": "b"}],
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True
    assert spy.get("delegate.started")["coordination"] == "none"
    assert captured["collaboration"] is False
    assert captured["note_wall"] is None
    assert t._note_wall is None
    assert not any(e.type == EventType.TEAM_NOTE_POSTED for e in sink._history)  # noqa: SLF001


async def test_multi_worker_coordination_wall_grants_note_channel(monkeypatch):
    """coordination=wall：行为与旧「多节点即建墙」一致。"""
    from agentcore.runtime.runs.notewall import NoteWall
    from agentcore.runtime.runs.types import RunPhase, RunState

    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    captured: dict = {}

    async def _exec(spec, completed):  # noqa: ANN001
        return RunState(phase=RunPhase.COMPLETED, content="OK")

    def _capture_build(**kwargs):  # noqa: ANN003
        captured["collaboration"] = kwargs.get("collaboration")
        captured["note_wall"] = kwargs.get("note_wall")
        return _exec

    monkeypatch.setattr("agentcore.runtime.runs.build_agent_executor", _capture_build)
    t = tool(Provider([]))
    result = await t.execute(
        {
            "tasks": [{"role": "A", "task": "a"}, {"role": "B", "task": "b"}],
            "coordination": "wall",
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True
    assert spy.get("delegate.started")["coordination"] == "wall"
    assert captured["collaboration"] is True
    assert isinstance(captured["note_wall"], NoteWall)
    assert t._note_wall is captured["note_wall"]


async def test_seed_notes_implies_wall_even_when_none(monkeypatch):
    """非空 seed_notes 隐含升级为 wall（即使显式 none）。"""
    from agentcore.runtime.events import EventType
    from agentcore.runtime.runs.types import RunPhase, RunState

    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    captured: dict = {}

    async def _exec(spec, completed):  # noqa: ANN001
        return RunState(phase=RunPhase.COMPLETED, content="OK")

    def _capture_build(**kwargs):  # noqa: ANN003
        captured["collaboration"] = kwargs.get("collaboration")
        captured["note_wall"] = kwargs.get("note_wall")
        return _exec

    monkeypatch.setattr("agentcore.runtime.runs.build_agent_executor", _capture_build)
    sink = EventSink()
    t = tool(Provider([]), sink=sink)
    result = await t.execute(
        {
            "tasks": [{"role": "A", "task": "a"}, {"role": "B", "task": "b"}],
            "coordination": "none",
            "seed_notes": [{"kind": "decision", "text": "接口用 REST"}],
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True
    assert spy.get("delegate.started")["coordination"] == "wall"
    assert captured["collaboration"] is True
    assert captured["note_wall"] is not None
    notes = [e for e in sink._history if e.type == EventType.TEAM_NOTE_POSTED]  # noqa: SLF001
    assert len(notes) == 1
    assert notes[0].payload["source"] == "ceo"
    assert notes[0].payload["text"] == "接口用 REST"


async def test_delegate_started_logs_who_what_and_first_wave_parallel(monkeypatch):
    # 决策可观测: delegate.started must carry「派了谁·干什么」(agents) + 首波扇出 (parallel),
    # not just a node count — so an offline analysis can see the delegation's input basis.
    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    t = tool(Provider(["AOUT", "BOUT"]))
    await t.execute(
        {
            "tasks": [
                {"role": "研究员", "task": "调研市场规模"},
                {"role": "写手", "task": "撰写初稿"},
            ]
        },
        ctx(),
    )
    started = spy.get("delegate.started")
    assert started["nodes"] == 2
    assert started["call"] == 1
    # both nodes are dependency-free → the whole batch is one parallel wave
    assert started["parallel"] == 2
    # who + what, in plan order — the delegation's actual content
    assert started["agents"] == ["研究员: 调研市场规模", "写手: 撰写初稿"]


async def test_delegate_started_parallel_reflects_dag_first_wave(monkeypatch):
    # A DAG (s2 depends_on s1) is NOT fully parallel: the first-wave width is 1 (only s1
    # has no deps), which `parallel` must reflect even though `nodes` is 2.
    spy = LogSpy()
    monkeypatch.setattr(delegate_tool_mod, "logger", spy)
    t = tool(Provider([_upstream_body("UP"), _upstream_body("FINAL")]))
    await t.execute(
        {
            "tasks": [
                {"id": "s1", "role": "研究员", "task": "调研"},
                {"id": "s2", "role": "写手", "task": "撰写", "depends_on": ["s1"]},
            ]
        },
        ctx(),
    )
    started = spy.get("delegate.started")
    assert started["nodes"] == 2
    assert started["parallel"] == 1


async def test_empty_tasks_rejected():
    t = tool(Provider([]))
    result = await t.execute({"tasks": []}, ctx())
    assert result.success is False
    assert result.is_terminal is False
    assert result.error
    assert result.contract_failure is True
    # Error text lives only in ``error`` — duplicate fill into ``output`` made
    # tool_exec join the same string twice for the model / UI.
    assert result.output == ""


async def test_all_invalid_tasks_rejected():
    t = tool(Provider([]))
    result = await t.execute({"tasks": [{"role": "A"}]}, ctx())
    assert result.success is False
    assert result.error
    assert result.contract_failure is True


async def test_build_plan_validation_contract_failure_skips_circuit_breaker():
    """depends_on / 参数校验打回标 contract_failure → 连拒不进熔断。"""
    from agentcore.runtime.loop_controller import LoopController, ToolAttempt

    t = tool(Provider([]))
    result = await t.execute(
        {
            "tasks": [
                {"id": "a", "role": "A", "task": "a"},
                {"id": "b", "role": "B", "task": "b", "depends_on": ["不存在的上游"]},
            ]
        },
        ctx(),
    )
    assert result.success is False
    assert result.contract_failure is True

    c = LoopController()
    for i in range(5):
        c.record(
            [
                ToolAttempt(
                    f"fp{i}",
                    "delegate",
                    success=False,
                    contract_failure=True,
                )
            ]
        )
        assert not c.tool_circuit_breaker()


async def test_worker_usage_accumulates_across_calls():
    usage = TokenUsage(
        input_tokens=10,
        output_tokens=5,
        reasoning_tokens=2,
        cache_hit_tokens=6,
        cache_miss_tokens=4,
    )
    t = tool(Provider(["X", "Y", "Z", "W"], usage=usage))
    first = await t.execute({"tasks": [{"role": "A", "task": "a"}]}, ctx())
    assert first.metadata["input_tokens"] == 10
    assert first.metadata["cache_hit_tokens"] == 6
    assert t.usage == {
        "input": 10,
        "output": 5,
        "reasoning": 2,
        "cache_hit": 6,
        "cache_miss": 4,
    }
    await t.execute({"tasks": [{"role": "B", "task": "b"}]}, ctx())
    assert t.usage == {
        "input": 20,
        "output": 10,
        "reasoning": 4,
        "cache_hit": 12,
        "cache_miss": 8,
    }


async def test_emits_plan_and_lifecycle_events():
    sink = EventSink()
    t = tool(Provider(["X"]), sink=sink)
    await t.execute({"tasks": [{"role": "A", "task": "做A"}]}, ctx())
    sink.close()
    types = [e.type async for e in sink]
    assert EventType.RUN_PLAN in types
    assert EventType.RUN_STARTED in types
    assert EventType.RUN_COMPLETED in types
    assert EventType.RUN_PROGRESS in types


async def test_run_plan_carries_stance_and_group_tags():
    sink = EventSink()
    t = tool(Provider(["PRO", "CON"]), sink=sink)
    await t.execute(
        {
            "tasks": [
                {"role": "正方", "task": "支持", "stance": "pro", "group": "g1"},
                {"role": "反方", "task": "反对", "stance": "con", "group": "g1"},
            ]
        },
        ctx(),
    )
    sink.close()
    plan_runs = [r async for e in sink if e.type == EventType.RUN_PLAN for r in e.payload["runs"]]
    by_task = {r["task"]: r for r in plan_runs}
    assert by_task["支持"]["stance"] == "pro"
    assert by_task["支持"]["group"] == "g1"
    assert by_task["反对"]["stance"] == "con"
    assert by_task["反对"]["group"] == "g1"


async def test_run_plan_carries_round_tag():
    sink = EventSink()
    t = tool(Provider(["R1", "R2"]), sink=sink)
    await t.execute(
        {
            "tasks": [
                {"id": "p1", "role": "正方", "task": "首轮", "stance": "pro", "round": 1},
                {
                    "id": "p2",
                    "role": "正方",
                    "task": "次轮",
                    "stance": "pro",
                    "round": 2,
                    "depends_on": ["p1"],
                },
            ]
        },
        ctx(),
    )
    sink.close()
    plan_runs = [r async for e in sink if e.type == EventType.RUN_PLAN for r in e.payload["runs"]]
    by_task = {r["task"]: r for r in plan_runs}
    assert by_task["首轮"]["round"] == 1
    assert by_task["次轮"]["round"] == 2


async def test_run_plan_omits_tags_for_ordinary_batch():
    sink = EventSink()
    t = tool(Provider(["X", "Y"]), sink=sink)
    await t.execute({"tasks": [{"role": "A", "task": "a"}, {"role": "B", "task": "b"}]}, ctx())
    sink.close()
    plan_runs = [r async for e in sink if e.type == EventType.RUN_PLAN for r in e.payload["runs"]]
    assert plan_runs
    assert all("stance" not in r and "group" not in r and "round" not in r for r in plan_runs)


def test_task_description_matches_what_worker_actually_receives():
    t = tool(Provider([]))
    task_desc = t.schema.parameters["properties"]["tasks"]["items"]["properties"]["task"][
        "description"
    ]
    # Schema 瘦身：task 描述强调自包含 + worker 看不到完整历史（细节进 skill）。
    assert "自包含" in task_desc
    assert "看不到完整历史" in task_desc


async def test_playbook_instantiates_whole_team_and_runs():
    # 拆·playbook 固化 (§2.1): naming a固化形状 + slots expands to a full team and flows through the
    # SAME pipeline as a hand-written tasks array (compare_options → 2 evaluators + 1 summary).
    t = tool(Provider([]))
    result = await t.execute(
        {"playbook": "compare_options", "playbook_args": {"question": "选 A 还是 B", "options": ["A", "B"]}},
        ctx(),
    )
    assert result.success is True
    assert result.is_terminal is False
    assert "汇总分析师" in result.output  # the summary role the playbook minted


async def test_playbook_unknown_name_rejected():
    t = tool(Provider([]))
    result = await t.execute({"playbook": "does_not_exist"}, ctx())
    assert result.success is False
    assert "未知 playbook" in (result.error or "")


async def test_playbook_missing_required_slot_rejected():
    t = tool(Provider([]))
    result = await t.execute({"playbook": "research_report", "playbook_args": {}}, ctx())
    assert result.success is False
    assert "topic" in (result.error or "")


async def test_playbook_and_tasks_are_mutually_exclusive():
    t = tool(Provider([]))
    result = await t.execute(
        {
            "playbook": "research_report",
            "playbook_args": {"topic": "X"},
            "tasks": [{"role": "a", "task": "b"}],
        },
        ctx(),
    )
    assert result.success is False
    assert "二选一" in (result.error or "")
    assert "手写 tasks" in (result.error or "")
    assert result.contract_failure is True


async def test_playbook_xor_and_hoist_conflict_skip_circuit_breaker():
    """S5 R1：playbook⊕tasks / 冲突内嵌 criteria 连拒须标 contract_failure，勿熔断 delegate。"""
    from agentcore.runtime.loop_controller import LoopController, ToolAttempt

    t = tool(Provider([]))
    xor = await t.execute(
        {
            "playbook_id": "build_feature",
            "playbook_args": {"feature": "CLI"},
            "tasks": [
                {"role": "实现", "task": "写 CLI"},
                {"role": "测试", "task": "写测试"},
            ],
        },
        ctx(),
    )
    assert xor.success is False
    assert xor.contract_failure is True

    hoist = await t.execute(
        {
            "playbook_id": "none",
            "playbook_none_reason": "简单双任务流水线",
            "tasks": [
                {
                    "role": "实现",
                    "task": "写 CLI",
                    "completion_criteria": {
                        "type": "custom",
                        "description": "包文件已创建",
                    },
                },
                {
                    "role": "测试",
                    "task": "写测试",
                    "completion_criteria": {
                        "type": "custom",
                        "description": "pytest 通过",
                    },
                },
            ],
        },
        ctx(),
    )
    assert hoist.success is False
    assert hoist.contract_failure is True
    assert "顶层" in (hoist.error or "") or "tasks[].completion_criteria" in (
        hoist.error or ""
    )

    c = LoopController()
    for i, res in enumerate((xor, hoist, xor)):
        c.record(
            [
                ToolAttempt(
                    f"fp{i}",
                    "delegate",
                    success=False,
                    contract_failure=res.contract_failure,
                )
            ]
        )
        assert not c.tool_circuit_breaker().disabled


def test_schema_cues_xor_and_top_level_completion_criteria():
    t = tool(Provider([]))
    assert "二选一" in t.schema.description
    assert "completion_criteria 仅顶层" in t.schema.description
    props = t.schema.parameters["properties"]
    cc = props["completion_criteria"]
    assert "顶层" in cc.get("description", "")
    assert "tasks[]" in cc.get("description", "")
    assert "runtime_ready" in cc.get("description", "")
    string_enum = next(
        branch["enum"] for branch in cc["oneOf"] if branch.get("type") == "string"
    )
    assert set(string_enum) == {"files_written", "code_verified", "runtime_ready"}
    t = tool(Provider([]))
    params = t.schema.parameters
    props = params["properties"]
    assert set(props["playbook"]["enum"]) == {
        "research_report",
        "build_feature",
        "repair_code",
        "build_website",
        "build_toolshed",
        "build_website_verify",
        "compare_options",
        "organize_folder",
        "multi_lens_research",
    }
    assert "playbook_args" in props
    # tasks is no longer HARD-required (playbook is an alternative entry); runtime enforces XOR.
    assert "tasks" not in params.get("required", [])
    coord = props["coordination"]
    assert coord["enum"] == ["wall", "none"]
    assert coord.get("default") == "none"


def test_strict_description_separates_rework_from_disposition():
    t = tool(Provider([]))
    deliverable_props = t.schema.parameters["properties"]["tasks"]["items"]["properties"]["deliverable"]
    strict_desc = deliverable_props["properties"]["strict"]["description"]
    assert "硬退" in strict_desc
    assert "软" in strict_desc
    assert "必须返工" not in strict_desc
    # Schema 瘦身：deliverable 总述指向 skill；硬退/软接受语义留在 strict 字段。
    deliverable_desc = deliverable_props["description"]
    assert "form" in deliverable_desc
    assert "team_orchestration_advanced" in deliverable_desc
