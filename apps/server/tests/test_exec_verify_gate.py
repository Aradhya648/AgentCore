"""Tests for run/open-verify capability strategy gate (仿 test_team_gate)."""

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.engine.governance import (
    create_loop_controller,
    exec_verify_ask_prompt,
    exec_verify_ask_text_exit_prompt,
    exec_verify_delegate_prompt,
    maybe_inject_exec_verify_gate,
    paste_writeback_delegate_prompt,
)
from agentcore.runtime.runs.exec_verify import (
    has_clear_verifiable_artifact_path,
    is_open_browser_verify_intent,
    is_open_local_app_intent,
    is_paste_writeback_intent,
    is_run_fix_script_intent,
    resolve_exec_verify_terminal,
)

_INV = frozenset({"file_list", "file_read", "grep", "web_search"})

_PASTE_MSG = (
    "下面这段 Python 跑起来报错，帮我找出坑并给出能跑的修复版，改完写回同文件：\n\n"
    "```python\ndef avg(nums):\n    return sum(nums) / len(nums)\n\n"
    "print(avg([]))\n```"
)


def test_run_fix_intent_narrow_match():
    assert is_run_fix_script_intent(
        "帮我跑一下 scripts/smoke_test.py，看看报什么错，有问题就修。"
    )
    assert is_run_fix_script_intent("请运行一下这个脚本看看报错")
    # 轻问 / 概念直答不被误伤
    assert not is_run_fix_script_intent("用一句话解释什么是幂等性（idempotency）。")
    assert not is_run_fix_script_intent(
        "终端里出现 `ModuleNotFoundError: No module named 'requests'`，这是什么意思？"
    )
    assert not is_run_fix_script_intent("你好呀，今天怎么样？")


def test_open_browser_verify_intent_narrow_match():
    assert is_open_browser_verify_intent(
        "刚才做好的那个页面，你能在本地直接打开浏览器帮我验证一下能不能用吗？"
    )
    assert is_open_browser_verify_intent("请打开浏览器验证 site/index.html")
    assert not is_open_browser_verify_intent("用三四百字聊聊开源许可证，直接回复就行。")
    assert not is_open_browser_verify_intent("Python 里 list 和 tuple 有什么区别？")


def test_open_local_app_intent_narrow_match():
    assert is_open_local_app_intent("你能帮我直接打开这个软件吗。")
    assert is_open_local_app_intent("请帮我打开这个应用")
    # 浏览器验证不走本分支
    assert not is_open_local_app_intent("请打开浏览器验证 site/index.html")
    assert not is_open_local_app_intent("用一句话解释什么是幂等性。")


def test_paste_writeback_intent_narrow_match():
    assert is_paste_writeback_intent(_PASTE_MSG)
    assert not is_paste_writeback_intent(
        "终端里出现 `ModuleNotFoundError: No module named 'requests'`，这是什么意思？"
    )
    assert not is_paste_writeback_intent("把 config.yaml 的 debug 改成 true")


def test_clear_artifact_path_heuristic():
    assert has_clear_verifiable_artifact_path("请打开浏览器验证 site/index.html")
    assert has_clear_verifiable_artifact_path("跑一下 scripts/smoke_test.py")
    assert not has_clear_verifiable_artifact_path(
        "刚才做好的那个页面，你能在本地直接打开浏览器帮我验证一下能不能用吗？"
    )


def test_strategy_table_resolve():
    assert (
        resolve_exec_verify_terminal(
            run_fix=True,
            open_verify=False,
            code_execute=True,
            browser=False,
            clear_artifact_path=True,
        )
        == "delegate"
    )
    assert (
        resolve_exec_verify_terminal(
            run_fix=True,
            open_verify=False,
            code_execute=False,
            browser=False,
            clear_artifact_path=True,
        )
        == "ask_user"
    )
    assert (
        resolve_exec_verify_terminal(
            run_fix=False,
            open_verify=True,
            code_execute=False,
            browser=False,
            clear_artifact_path=False,
        )
        == "ask_user"
    )
    assert (
        resolve_exec_verify_terminal(
            run_fix=False,
            open_verify=True,
            code_execute=True,
            browser=True,
            clear_artifact_path=True,
        )
        == "delegate"
    )
    assert (
        resolve_exec_verify_terminal(
            run_fix=False,
            open_verify=False,
            code_execute=True,
            browser=True,
            clear_artifact_path=True,
        )
        is None
    )
    assert (
        resolve_exec_verify_terminal(
            run_fix=False,
            open_verify=False,
            open_app=True,
            code_execute=False,
            browser=False,
            local_open=False,
            clear_artifact_path=False,
        )
        == "ask_user"
    )
    assert (
        resolve_exec_verify_terminal(
            run_fix=False,
            open_verify=False,
            open_app=True,
            code_execute=False,
            browser=False,
            local_open=True,
            clear_artifact_path=False,
        )
        == "delegate"
    )
    assert (
        resolve_exec_verify_terminal(
            run_fix=False,
            open_verify=False,
            paste_writeback=True,
            code_execute=False,
            browser=False,
            clear_artifact_path=False,
        )
        == "delegate"
    )


def test_gate_ask_when_no_exec_for_run_script():
    controller = create_loop_controller(_INV)
    disabled: set[str] = set()
    messages = [
        LLMMessage(
            role="user",
            content="帮我跑一下 scripts/smoke_test.py，看看报什么错，有问题就修。",
        )
    ]
    assert (
        maybe_inject_exec_verify_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            code_execute=False,
            browser=False,
            disabled_tools=disabled,
            investigation_tools=_INV,
            ask_user_available=True,
        )
        is True
    )
    assert controller.exec_verify_gate_fired is True
    assert controller.exec_verify_text_exit is False
    assert disabled == set(_INV) | {"delegate", "debate"}
    nudge = next(m.content or "" for m in messages if "能力策略" in (m.content or ""))
    assert "ask_user" in nudge
    assert "探路与委派工具已收回" in nudge
    # one-shot
    assert (
        maybe_inject_exec_verify_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=1,
            role="captain",
            code_execute=False,
            browser=False,
            disabled_tools=disabled,
            investigation_tools=_INV,
        )
        is False
    )


def test_gate_ask_without_ask_user_forces_text_exit():
    """Eval / approvals_enabled=False: no ask_user → prose close, not max_rounds spin."""
    controller = create_loop_controller(_INV)
    disabled: set[str] = set()
    messages = [LLMMessage(role="user", content="你能帮我直接打开这个软件吗。")]
    assert (
        maybe_inject_exec_verify_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            code_execute=False,
            browser=False,
            local_open=False,
            disabled_tools=disabled,
            investigation_tools=_INV,
            ask_user_available=False,
        )
        is True
    )
    assert controller.exec_verify_gate_fired is True
    assert controller.exec_verify_text_exit is True
    assert disabled == set(_INV) | {"delegate", "debate"}
    assert "delegate" in disabled
    nudge = next(m.content or "" for m in messages if "能力策略" in (m.content or ""))
    assert "未装配 ask_user" in nudge
    assert "工具面已清空" in nudge
    assert "立即结束" in nudge


def test_gate_ask_with_ask_user_keeps_card_path():
    controller = create_loop_controller(_INV)
    disabled: set[str] = set()
    messages = [LLMMessage(role="user", content="你能帮我直接打开这个软件吗。")]
    assert (
        maybe_inject_exec_verify_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            code_execute=False,
            browser=False,
            local_open=False,
            disabled_tools=disabled,
            investigation_tools=_INV,
            ask_user_available=True,
        )
        is True
    )
    assert controller.exec_verify_text_exit is False
    assert disabled == set(_INV) | {"delegate", "debate"}
    nudge = next(m.content or "" for m in messages if "能力策略" in (m.content or ""))
    assert "请立即 ask_user" in nudge
    assert "未装配 ask_user" not in nudge


def test_gate_delegate_when_exec_ready():
    controller = create_loop_controller(_INV)
    disabled: set[str] = set()
    messages = [
        LLMMessage(
            role="user",
            content="帮我跑一下 scripts/smoke_test.py，看看报什么错，有问题就修。",
        )
    ]
    assert maybe_inject_exec_verify_gate(
        controller,
        messages=messages,
        run_id="r",
        round_idx=0,
        role="captain",
        code_execute=True,
        browser=False,
        disabled_tools=disabled,
        investigation_tools=_INV,
    )
    assert controller.exec_verify_text_exit is False
    nudge = next(m.content or "" for m in messages if "能力策略" in (m.content or ""))
    assert "delegate" in nudge
    assert "code_verified" in nudge
    assert disabled == set(_INV)


def test_gate_ask_open_verify_no_browser_or_unclear_path():
    controller = create_loop_controller(_INV)
    disabled: set[str] = set()
    messages = [
        LLMMessage(
            role="user",
            content="刚才做好的那个页面，你能在本地直接打开浏览器帮我验证一下能不能用吗？",
        )
    ]
    assert maybe_inject_exec_verify_gate(
        controller,
        messages=messages,
        run_id="r",
        round_idx=0,
        role="captain",
        code_execute=False,
        browser=False,
        disabled_tools=disabled,
        investigation_tools=_INV,
        ask_user_available=True,
    )
    assert controller.exec_verify_text_exit is False
    nudge = next(m.content or "" for m in messages if "能力策略" in (m.content or ""))
    assert "ask_user" in nudge
    assert disabled == set(_INV) | {"delegate", "debate"}


def test_gate_ask_open_app_without_local_open():
    controller = create_loop_controller(_INV)
    disabled: set[str] = set()
    messages = [LLMMessage(role="user", content="你能帮我直接打开这个软件吗。")]
    assert maybe_inject_exec_verify_gate(
        controller,
        messages=messages,
        run_id="r",
        round_idx=0,
        role="captain",
        code_execute=False,
        browser=False,
        local_open=False,
        disabled_tools=disabled,
        investigation_tools=_INV,
        ask_user_available=True,
    )
    assert controller.exec_verify_text_exit is False
    nudge = next(m.content or "" for m in messages if "能力策略" in (m.content or ""))
    assert "ask_user" in nudge
    assert disabled == set(_INV) | {"delegate", "debate"}
    assert "delegate" in disabled
    assert "debate" in disabled


def test_gate_delegate_paste_writeback_even_without_exec():
    controller = create_loop_controller(_INV)
    disabled: set[str] = set()
    messages = [LLMMessage(role="user", content=_PASTE_MSG)]
    assert maybe_inject_exec_verify_gate(
        controller,
        messages=messages,
        run_id="r",
        round_idx=0,
        role="captain",
        code_execute=False,
        browser=False,
        disabled_tools=disabled,
        investigation_tools=_INV,
    )
    nudge = next(m.content or "" for m in messages if "能力策略" in (m.content or ""))
    assert "delegate" in nudge
    assert "写回" in nudge
    assert "code_verified" not in nudge
    assert disabled == set(_INV)


def test_gate_skips_light_direct_chat():
    controller = create_loop_controller(_INV)
    disabled: set[str] = set()
    messages = [LLMMessage(role="user", content="用一句话解释什么是幂等性。")]
    assert (
        maybe_inject_exec_verify_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            code_execute=False,
            browser=False,
            disabled_tools=disabled,
            investigation_tools=_INV,
        )
        is False
    )
    assert disabled == set()
    assert controller.exec_verify_gate_fired is False
    assert controller.exec_verify_text_exit is False


def test_gate_prompt_copy_short():
    ask = exec_verify_ask_prompt()
    text_exit = exec_verify_ask_text_exit_prompt()
    dele = exec_verify_delegate_prompt()
    paste = paste_writeback_delegate_prompt()
    assert ask.startswith("[系统提示]")
    assert text_exit.startswith("[系统提示]")
    assert dele.startswith("[系统提示]")
    assert paste.startswith("[系统提示]")
    assert len(ask) < 220
    assert len(text_exit) < 260
    assert len(dele) < 200
    assert len(paste) < 160
