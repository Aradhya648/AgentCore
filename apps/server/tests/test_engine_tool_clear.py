"""回合内工具结果清理 (clear_tool_uses): pure-function + loop-integration tests.

The projection ``project_cleared_window`` collapses OLD re-fetchable read-only tool
results to a compact stable pointer in the model-facing window, while the canonical
``messages`` list keeps the full output (so resume / journal are byte-identical). These
tests pin: what gets cleared vs kept, the prefix-cache invariants (stable + monotonic
+ structure-preserving + idempotent), and the wiring into ``react_loop``.
"""

import json
from pathlib import Path

from agentcore.config import settings
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.llm.provider.protocol import LLMChunk, LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.engine import react_loop
from agentcore.runtime.engine.tool_clear import cleared_placeholder, project_cleared_window
from agentcore.runtime.events import EventSink
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.llm_helpers import make_profile_params

CLEARABLE = frozenset({"file_read", "grep", "web_search"})


def _read_pair(call_id: str, path: str, result: str, *, tool: str = "file_read") -> list[LLMMessage]:
    """An assistant tool-call round + its tool result, as the loop accumulates them."""
    return [
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id=call_id,
                    function=ToolCallFunction(name=tool, arguments=json.dumps({"path": path})),
                )
            ],
        ),
        LLMMessage(role="tool", content=result, tool_call_id=call_id),
    ]


def _window(n_pairs: int, *, size: int = 200, tool: str = "file_read") -> list[LLMMessage]:
    msgs: list[LLMMessage] = [LLMMessage(role="user", content="go")]
    for i in range(n_pairs):
        msgs += _read_pair(f"c{i}", f"src/f{i}.py", "X" * size, tool=tool)
    return msgs


def _cleared_ids(messages: list[LLMMessage]) -> list[str]:
    return [
        m.tool_call_id
        for m in messages
        if m.role == "tool" and (m.content or "").startswith("[已清理")
    ]


# ── pure function ───────────────────────────────────────────────────────────


def test_keeps_recent_clears_old():
    msgs = _window(8)  # 8 big read results
    out = project_cleared_window(msgs, clearable_tools=CLEARABLE, keep_recent=2, min_chars=100)
    # First 6 cleared, last 2 (c6, c7) kept verbatim.
    assert _cleared_ids(out) == [f"c{i}" for i in range(6)]
    kept = [m for m in out if m.role == "tool" and not (m.content or "").startswith("[已清理")]
    assert [m.tool_call_id for m in kept] == ["c6", "c7"]
    assert all(len(m.content or "") == 200 for m in kept)


def test_small_results_not_cleared():
    msgs = _window(8, size=50)  # every result < min_chars
    out = project_cleared_window(msgs, clearable_tools=CLEARABLE, keep_recent=2, min_chars=100)
    assert out is msgs  # no-op → same object


def test_non_investigation_tool_not_cleared():
    msgs = _window(8, tool="code_execute")  # not in clearable set
    out = project_cleared_window(msgs, clearable_tools=CLEARABLE, keep_recent=2, min_chars=100)
    assert out is msgs


def test_injected_user_and_assistant_untouched():
    msgs = _window(4)
    msgs.append(LLMMessage(role="user", content="[系统提示] 复盘一下进度。"))  # a nudge/reflection
    out = project_cleared_window(msgs, clearable_tools=CLEARABLE, keep_recent=1, min_chars=100)
    # the injected user steer and all assistant messages survive verbatim
    assert any(m.role == "user" and m.content == "[系统提示] 复盘一下进度。" for m in out)
    assert all(o.content == n.content for o, n in zip(msgs, out, strict=True) if o.role == "assistant")


def test_structure_preserved_no_orphans():
    msgs = _window(8)
    out = project_cleared_window(msgs, clearable_tools=CLEARABLE, keep_recent=2, min_chars=100)
    # every tool message still pairs with an assistant tool_call of the same id
    issued = {
        c.id for m in out if m.role == "assistant" and m.tool_calls for c in m.tool_calls
    }
    tool_ids = [m.tool_call_id for m in out if m.role == "tool"]
    assert len(tool_ids) == 8  # none dropped
    assert all(tid in issued for tid in tool_ids)  # no orphan tool message


def test_placeholder_stable_and_monotonic():
    # Same cleared result yields byte-identical pointer across two successive rounds
    # (prefix-cache invariant), and clearing only grows (monotonic).
    win_k = project_cleared_window(_window(5), clearable_tools=CLEARABLE, keep_recent=2, min_chars=10)
    win_k1 = project_cleared_window(_window(6), clearable_tools=CLEARABLE, keep_recent=2, min_chars=10)

    def cleared_content(window: list[LLMMessage], call_id: str) -> str | None:
        for m in window:
            if m.role == "tool" and m.tool_call_id == call_id:
                return m.content
        return None

    # c0 is cleared in both; its pointer bytes must be identical.
    assert cleared_content(win_k, "c0").startswith("[已清理")
    assert cleared_content(win_k, "c0") == cleared_content(win_k1, "c0")
    # monotonic: everything cleared at round K is still cleared at round K+1.
    assert set(_cleared_ids(win_k)).issubset(set(_cleared_ids(win_k1)))


def test_idempotent():
    msgs = _window(8)
    once = project_cleared_window(msgs, clearable_tools=CLEARABLE, keep_recent=2, min_chars=100)
    twice = project_cleared_window(once, clearable_tools=CLEARABLE, keep_recent=2, min_chars=100)
    assert [m.content for m in twice] == [m.content for m in once]


def test_placeholder_names_the_call():
    ph = cleared_placeholder("file_read", json.dumps({"path": "src/foo.py"}), 8421)
    assert "file_read" in ph and "src/foo.py" in ph and "8421" in ph
    # deterministic
    assert ph == cleared_placeholder("file_read", json.dumps({"path": "src/foo.py"}), 8421)


def test_empty_clearable_is_noop():
    msgs = _window(8)
    assert project_cleared_window(msgs, clearable_tools=frozenset(), keep_recent=2, min_chars=100) is msgs


# ── loop wiring ─────────────────────────────────────────────────────────────


class _FakeReadTool:
    """A read-only NEVER-approval FILESYSTEM tool so the loop classifies it as an
    investigation tool (clearable). Never executed by these tests (the window is
    pre-seeded and the provider finishes round 0)."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_read",
            description="read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments, context) -> ToolResult:  # noqa: ANN001 - duck-typed
        return ToolResult(tool_call_id="", success=True, output="unused")


class _CapturingProvider:
    """Records the request window each round, then yields scripted chunks."""

    def __init__(self, rounds: list[list[LLMChunk]]) -> None:
        self._rounds = rounds
        self.calls = 0
        self.windows: list[list[LLMMessage]] = []

    async def stream(self, request):  # noqa: ANN001 - duck-typed for the loop
        self.windows.append(list(request.messages))
        chunks = self._rounds[self.calls] if self.calls < len(self._rounds) else []
        self.calls += 1
        for chunk in chunks:
            yield chunk


def _context() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )


async def _run_loop(provider: _CapturingProvider) -> None:
    registry = ToolRegistry()
    registry.register(_FakeReadTool())
    messages = _window(8)  # pre-seeded prior reads
    profile = make_profile_params(max_rounds=4)
    await react_loop(
        messages=messages,
        llm=provider,
        tools=registry,
        sink=EventSink(),
        tool_context=_context(),
        profile=profile,
        turn_model="m",
    )


async def test_loop_clears_old_reads_in_request_window(monkeypatch):
    monkeypatch.setattr(settings, "engine_tool_clear_keep_recent", 2)
    monkeypatch.setattr(settings, "engine_tool_clear_min_chars", 100)
    provider = _CapturingProvider([[LLMChunk(delta_content="调查完成，结论如下。")]])
    await _run_loop(provider)
    window = provider.windows[0]
    # 6 old read results cleared, 2 most-recent kept full — the canonical messages
    # the loop holds are untouched (only the request view is projected).
    assert len(_cleared_ids(window)) == 6
    kept = [m for m in window if m.role == "tool" and not (m.content or "").startswith("[已清理")]
    assert len(kept) == 2 and all(len(m.content or "") == 200 for m in kept)


async def test_loop_no_clear_when_keep_recent_high(monkeypatch):
    monkeypatch.setattr(settings, "engine_tool_clear_keep_recent", 100)  # effectively off
    monkeypatch.setattr(settings, "engine_tool_clear_min_chars", 100)
    provider = _CapturingProvider([[LLMChunk(delta_content="调查完成。")]])
    await _run_loop(provider)
    window = provider.windows[0]
    assert _cleared_ids(window) == []  # nothing cleared
    assert all(len(m.content or "") == 200 for m in window if m.role == "tool")


# ── R1: file_read digest + sticky re-read ───────────────────────────────────


def test_file_read_clear_keeps_structural_summary_under_min_chars():
    from agentcore.runtime.engine.tool_clear import structural_file_read_summary

    md = "# Title\n\n## Section\n\n" + ("body " * 400)
    path = "docs/spec.md"
    msgs = [LLMMessage(role="user", content="go")]
    for i in range(4):
        msgs += _read_pair(f"c{i}", path if i < 2 else f"other/{i}.md", md)
    out = project_cleared_window(
        msgs,
        clearable_tools=CLEARABLE,
        keep_recent=1,
        min_chars=200,
        summary_max_chars=1200,
    )
    cleared = [
        m
        for m in out
        if m.role == "tool" and (m.content or "").startswith("[已清理")
    ]
    assert cleared
    for m in cleared:
        assert len(m.content or "") < 200
        # file_read of the md path should carry a digest when room allows
        if "docs/spec.md" in (m.content or ""):
            assert "自动" in (m.content or "") or "标题" in (m.content or "")
    # pure + idempotent
    digest = structural_file_read_summary(path, md, max_chars=400)
    assert digest is not None and "Title" in digest
    assert digest == structural_file_read_summary(path, md, max_chars=400)
    once = project_cleared_window(
        msgs, clearable_tools=CLEARABLE, keep_recent=1, min_chars=200, summary_max_chars=1200
    )
    twice = project_cleared_window(
        once, clearable_tools=CLEARABLE, keep_recent=1, min_chars=200, summary_max_chars=1200
    )
    assert [m.content for m in twice] == [m.content for m in once]


def test_file_read_summary_max_chars_zero_is_pointer_only():
    md = "# H\n" + ("x" * 300)
    msgs = _window(4, size=300)
    # overwrite first result with structured md for the named path
    msgs = [LLMMessage(role="user", content="go")]
    for i in range(4):
        msgs += _read_pair(f"c{i}", f"f{i}.md", md)
    out = project_cleared_window(
        msgs,
        clearable_tools=CLEARABLE,
        keep_recent=1,
        min_chars=100,
        summary_max_chars=0,
    )
    for m in out:
        if m.role == "tool" and (m.content or "").startswith("[已清理"):
            assert "自动" not in (m.content or "")
            assert "\n" not in (m.content or "")


def test_grep_clear_stays_pointer_only_even_with_summary_budget():
    big = "hit " * 80
    msgs = [LLMMessage(role="user", content="go")]
    for i in range(4):
        msgs += _read_pair(f"c{i}", f"f{i}.py", big, tool="grep")
    out = project_cleared_window(
        msgs,
        clearable_tools=CLEARABLE,
        keep_recent=1,
        min_chars=100,
        summary_max_chars=1200,
    )
    for m in out:
        if m.role == "tool" and (m.content or "").startswith("[已清理"):
            assert "自动" not in (m.content or "")


def test_apply_file_read_clear_state_grants_only_when_zero_verbatim():
    from agentcore.runtime.engine.tool_clear import apply_file_read_clear_state
    from agentcore.runtime.runs.constants import FILE_READ_SAME_PATH_MAX

    body = "X" * 200
    # Same path read to MAX; keep_recent=1 ⇒ one verbatim.
    msgs = [LLMMessage(role="user", content="go")]
    msgs += _read_pair("c0", "a.md", body)
    msgs += _read_pair("c1", "a.md", body)
    msgs += _read_pair("c2", "b.md", body)  # filler so a.md's first falls out
    msgs += _read_pair("c3", "c.md", body)

    ctx = _context()
    ctx.file_read_counts["a.md"] = FILE_READ_SAME_PATH_MAX
    # keep_recent=2 → c2,c3 kept; c0,c1 cleared → a.md zero verbatim → grant
    synced = apply_file_read_clear_state(
        ctx,
        msgs,
        investigation_tools=CLEARABLE,
        keep_recent=2,
        min_chars=100,
        summary_max_chars=0,
        reread_grant=1,
    )
    assert "a.md" not in (synced.file_read_verbatim_paths or frozenset())
    assert synced.file_read_reread_issued.get("a.md") is True
    assert synced.file_read_reread_remaining.get("a.md") == 1

    # Partial clear: keep_recent=3 keeps one a.md verbatim → no grant
    ctx2 = _context()
    ctx2.file_read_counts["a.md"] = FILE_READ_SAME_PATH_MAX
    partial = apply_file_read_clear_state(
        ctx2,
        msgs,
        investigation_tools=CLEARABLE,
        keep_recent=3,
        min_chars=100,
        summary_max_chars=0,
        reread_grant=1,
    )
    assert "a.md" in (partial.file_read_verbatim_paths or frozenset())
    assert "a.md" not in partial.file_read_reread_issued


def test_apply_file_read_clear_state_sticky_no_second_grant():
    from agentcore.runtime.engine.tool_clear import apply_file_read_clear_state
    from agentcore.runtime.runs.constants import FILE_READ_SAME_PATH_MAX

    body = "Y" * 200
    msgs = [LLMMessage(role="user", content="go")]
    msgs += _read_pair("a0", "a.md", body)
    msgs += _read_pair("a1", "a.md", body)
    msgs += _read_pair("f0", "filler0.md", body)
    msgs += _read_pair("f1", "filler1.md", body)
    # keep_recent=1 keeps only filler1 → a.md fully cleared → grant once.

    ctx = _context()
    ctx.file_read_counts["a.md"] = FILE_READ_SAME_PATH_MAX
    first = apply_file_read_clear_state(
        ctx,
        msgs,
        investigation_tools=CLEARABLE,
        keep_recent=1,
        min_chars=100,
        summary_max_chars=0,
        reread_grant=1,
    )
    assert "a.md" not in (first.file_read_verbatim_paths or frozenset())
    assert first.file_read_reread_remaining["a.md"] == 1
    # Simulate grant consumed, then another clear cycle — must not re-grant.
    first.file_read_reread_remaining["a.md"] = 0
    first.file_read_counts["a.md"] = FILE_READ_SAME_PATH_MAX + 1
    second = apply_file_read_clear_state(
        first,
        msgs,
        investigation_tools=CLEARABLE,
        keep_recent=1,
        min_chars=100,
        summary_max_chars=0,
        reread_grant=1,
    )
    assert second.file_read_reread_remaining["a.md"] == 0
    assert second.file_read_reread_issued["a.md"] is True


def test_canonical_messages_untouched_by_projection():
    """Journal / canonical keep full bodies — only the projected view clears."""
    msgs = _window(6, size=200)
    originals = [m.content for m in msgs if m.role == "tool"]
    out = project_cleared_window(
        msgs, clearable_tools=CLEARABLE, keep_recent=2, min_chars=100, summary_max_chars=400
    )
    assert out is not msgs
    assert [m.content for m in msgs if m.role == "tool"] == originals
