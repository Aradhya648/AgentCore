"""Structured checkpoint (plan_review) tests.

提问确认交互统一 P1 · D11：窄兜底已删。无 durable saver / transcript 时 plan_review
跳过挂起放行下游（不再假等待）。带 saver 的 continue/stop/adjust 见 test_durable.py。
"""


from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.interaction import InteractionRegistry
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.registry import ToolRegistry
from tests.delegate.conftest import CKPT_DAG, Provider, ctx, tool, tool_ckpt


async def test_checkpoint_skipped_without_durable_frame():
    """无 saver/transcript ⇒ persist 失败 ⇒ 跳过挂起，两 worker 都跑完。"""
    registry = InteractionRegistry()
    sink = EventSink()
    t = tool_ckpt(Provider(["S1OUT", "S2OUT"]), sink, registry, "conv1", timeout=5.0)
    result = await t.execute({"tasks": CKPT_DAG, "coordinate": False}, ctx())

    assert "S1OUT" in result.output
    assert "S2OUT" in result.output
    assert registry.list_pending("conv1") == []
    sink.close()
    types = [e.type async for e in sink]
    # 未落盘不 emit required（避免假卡）
    assert EventType.PLAN_REVIEW_REQUIRED not in types
    assert EventType.PLAN_REVIEW_RESOLVED not in types


async def test_checkpoint_timeout_setting_no_longer_auto_continues_via_narrow_net():
    """原窄兜底 timeout→continue 已删；无 frame 时直接放行，不发 resolved。"""
    registry = InteractionRegistry()
    sink = EventSink()
    t = tool_ckpt(Provider(["S1OUT", "S2OUT"]), sink, registry, "conv1", timeout=0.05)
    result = await t.execute({"tasks": CKPT_DAG, "coordinate": False}, ctx())
    assert "S1OUT" in result.output
    assert "S2OUT" in result.output
    sink.close()
    types = [e.type async for e in sink]
    assert EventType.PLAN_REVIEW_RESOLVED not in types


async def test_checkpoint_inert_when_disabled():
    sink = EventSink()
    t = tool(Provider(["S1OUT", "S2OUT"]), sink=sink)
    result = await t.execute({"tasks": CKPT_DAG, "coordinate": False}, ctx())
    assert "S1OUT" in result.output
    assert "S2OUT" in result.output
    sink.close()
    types = [e.type async for e in sink]
    assert EventType.PLAN_REVIEW_REQUIRED not in types


async def test_checkpoint_after_skipped_when_gate_off():
    """闸关（checkpoint_enabled=False）时含 checkpoint_after 的 DAG 不结构挂起。"""
    registry = InteractionRegistry()
    sink = EventSink()
    t = DelegateTool(
        llm=Provider(["S1OUT", "S2OUT"]),
        sink=sink,
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=ctx(),
        conversation_id="conv-gate-off",
        registry=registry,
        checkpoint_timeout_seconds=5.0,
        checkpoint_enabled=False,
    )
    result = await t.execute({"tasks": CKPT_DAG, "coordinate": False}, ctx())
    assert "S1OUT" in result.output
    assert "S2OUT" in result.output
    assert registry.list_pending("conv-gate-off") == []
    sink.close()
    types = [e.type async for e in sink]
    assert EventType.PLAN_REVIEW_REQUIRED not in types
    assert EventType.PLAN_REVIEW_RESOLVED not in types
