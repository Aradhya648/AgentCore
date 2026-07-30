"""Tests for convergence governance (runtime.loop_controller).

Pure logic — no LLM, no I/O. Covers the fingerprint, the three stuck patterns,
detection priority, and the two-strike NUDGE→FINALIZE ladder (including the
window clear that prevents a stale pattern from finalizing prematurely).
"""

from agentcore.runtime.loop_controller import (
    Intervention,
    LoopController,
    StuckReason,
    ToolAttempt,
    fingerprint_tool_call,
    progress_review_prompt,
)


def _ok(fp: str, name: str = "t") -> ToolAttempt:
    return ToolAttempt(fingerprint=fp, tool_name=name, success=True)


def _fail(fp: str, name: str = "t") -> ToolAttempt:
    return ToolAttempt(fingerprint=fp, tool_name=name, success=False)


# --- fingerprint ---


def test_fingerprint_same_name_and_args_match():
    assert fingerprint_tool_call("web_search", '{"q": "x"}') == fingerprint_tool_call(
        "web_search", '{"q": "x"}'
    )


def test_fingerprint_ignores_key_order():
    assert fingerprint_tool_call("t", '{"a": 1, "b": 2}') == fingerprint_tool_call(
        "t", '{"b": 2, "a": 1}'
    )


def test_fingerprint_differs_on_args_and_name():
    assert fingerprint_tool_call("t", '{"q": "x"}') != fingerprint_tool_call("t", '{"q": "y"}')
    assert fingerprint_tool_call("a", "{}") != fingerprint_tool_call("b", "{}")


def test_fingerprint_malformed_json_falls_back_to_raw():
    # Identical malformed strings still collide (verbatim repeat caught);
    # different malformed strings do not.
    assert fingerprint_tool_call("t", "not json") == fingerprint_tool_call("t", "not json")
    assert fingerprint_tool_call("t", "not json") != fingerprint_tool_call("t", "other junk")


def test_fingerprint_empty_args_stable():
    assert fingerprint_tool_call("t", "") == fingerprint_tool_call("t", "")


# --- detect: nothing below threshold ---


def test_detect_below_threshold_returns_none():
    c = LoopController()
    c.record([_ok("a"), _ok("a")])  # 2 < threshold 3
    assert c.detect() is None


def test_detect_distinct_calls_returns_none():
    c = LoopController()
    c.record([_ok("a"), _ok("b"), _ok("c"), _ok("d")])
    assert c.detect() is None


# --- detect: repeated identical call ---


def test_detect_repeated_call():
    c = LoopController()
    c.record([_ok("a"), _ok("a"), _ok("a")])
    signal = c.detect()
    assert signal is not None
    assert signal.reason is StuckReason.REPEATED_CALL
    assert signal.count == 3


def test_detect_repeated_call_across_rounds():
    c = LoopController()
    c.record([_ok("a")])
    c.record([_ok("a")])
    assert c.detect() is None  # only 2 so far
    c.record([_ok("a")])
    assert c.detect().reason is StuckReason.REPEATED_CALL


def test_detect_three_identical_parallel_calls_in_one_round():
    c = LoopController()
    c.record([_ok("a"), _ok("a"), _ok("a")])
    assert c.detect().reason is StuckReason.REPEATED_CALL


# --- detect: repeated failure takes priority ---


def test_detect_repeated_failure_priority_over_repeated_call():
    c = LoopController()
    c.record([_fail("a"), _fail("a"), _fail("a")])
    signal = c.detect()
    assert signal.reason is StuckReason.REPEATED_FAILURE
    assert signal.count == 3


def test_detect_mixed_success_is_repeated_call_not_failure():
    c = LoopController()
    c.record([_ok("a"), _fail("a"), _ok("a")])  # only 2 failures < threshold
    assert c.detect().reason is StuckReason.REPEATED_CALL


# --- detect: A-B-A-B alternation ---


def test_detect_alternating():
    c = LoopController()
    c.record([_ok("a"), _ok("b"), _ok("a"), _ok("b")])
    signal = c.detect()
    assert signal is not None
    assert signal.reason is StuckReason.ALTERNATING


def test_detect_not_alternating_when_same_fingerprint():
    c = LoopController()
    # a,a,a,a → repeated_call wins, not alternation
    c.record([_ok("a"), _ok("a"), _ok("a"), _ok("a")])
    assert c.detect().reason is StuckReason.REPEATED_CALL


# --- decide: two-strike ladder ---


def test_decide_continue_when_no_signal():
    c = LoopController()
    assert c.decide(None) is Intervention.CONTINUE


def test_decide_first_signal_nudges_then_finalizes():
    c = LoopController()
    c.record([_ok("a"), _ok("a"), _ok("a")])
    first = c.detect()
    assert c.decide(first) is Intervention.NUDGE
    # window was cleared by the nudge: a fresh repeat is needed to escalate
    assert c.detect() is None
    c.record([_ok("a"), _ok("a"), _ok("a")])
    second = c.detect()
    assert c.decide(second) is Intervention.FINALIZE


def test_nudge_clears_window_so_one_stale_repeat_does_not_finalize():
    c = LoopController()
    c.record([_ok("a"), _ok("a"), _ok("a")])
    c.decide(c.detect())  # NUDGE + clear
    # Model recovers: a single different call must NOT immediately finalize.
    c.record([_ok("b")])
    assert c.detect() is None


# --- B2: empty-response degraded ladder ---


def test_empty_response_continues_then_finalizes():
    # The default ladder: 1st empty retries on the same model (CONTINUE), and a
    # 2nd consecutive empty → FINALIZE (the turn ends degraded, not blank).
    c = LoopController(empty_threshold=2)
    c.note_empty_round(True)
    assert c.empty_response_action() is Intervention.CONTINUE
    c.note_empty_round(True)
    assert c.empty_response_action() is Intervention.FINALIZE


def test_empty_streak_resets_on_nonempty_round():
    # A real answer / tool call between empties breaks the streak, so only
    # *consecutive* empties escalate.
    c = LoopController(empty_threshold=2)
    c.note_empty_round(True)
    c.note_empty_round(False)  # recovered
    c.note_empty_round(True)  # streak restarts at 1
    assert c.empty_response_action() is Intervention.CONTINUE


# --- B2: tool failure circuit breaker ---


def test_circuit_breaker_warns_at_warn_threshold():
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    c.record([_fail("a", "t")])  # 1 failure (distinct args, same tool)
    assert not c.tool_circuit_breaker()  # below warn
    c.record([_fail("b", "t")])  # 2 failures
    cb = c.tool_circuit_breaker()
    assert cb.warned == ("t",)
    assert cb.disabled == ()


def test_circuit_breaker_disables_at_disable_threshold_and_is_idempotent():
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    c.record([_fail("a", "t"), _fail("b", "t")])
    assert c.tool_circuit_breaker().warned == ("t",)
    c.record([_fail("c", "t")])  # 3rd failure
    cb = c.tool_circuit_breaker()
    assert cb.disabled == ("t",)
    assert cb.warned == ()  # not re-warned
    # already disabled → no further transitions fire for this tool
    c.record([_fail("d", "t")])
    assert not c.tool_circuit_breaker()


def test_circuit_breaker_leaps_straight_to_disable_without_redundant_warn():
    # 3 failures arrive before any check → the tool is disabled outright (no warn).
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    c.record([_fail("a", "t"), _fail("b", "t"), _fail("c", "t")])
    cb = c.tool_circuit_breaker()
    assert cb.disabled == ("t",)
    assert cb.warned == ()


def test_circuit_breaker_read_url_warn_and_disable_use_stop_read_steer():
    """read_url steers must not say「换不同的输入」(that fuels URL thrashing)."""
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    c.record([_fail("a", "read_url"), _fail("b", "read_url")])
    warn = c.tool_circuit_breaker()
    assert warn.warned == ("read_url",)
    msg = warn.message() or ""
    assert "换不同的输入" not in msg
    assert "read_url" in msg
    assert "web_search" in msg or "收口" in msg or "重读" in msg

    c.record([_fail("c", "read_url")])
    disable = c.tool_circuit_breaker()
    assert disable.disabled == ("read_url",)
    dmsg = disable.message() or ""
    assert "换不同的输入" not in dmsg
    assert "停用" in dmsg
    assert "web_search" in dmsg or "收口" in dmsg


def test_circuit_breaker_counts_failures_per_tool_and_ignores_success():
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    c.record([_ok("a", "t"), _ok("b", "t")])  # successes never count
    c.record([_fail("c", "u")])  # a different tool's single failure
    assert not c.tool_circuit_breaker()


def test_circuit_breaker_ignores_policy_failures():
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    policy = ToolAttempt("a", "read_url", success=False, policy_failure=True)
    c.record([policy, policy, policy])
    assert not c.tool_circuit_breaker()


def test_circuit_breaker_ignores_approval_denial_policy_failures():
    # Approval denials are stamped policy_failure=True in tool_exec — same posture
    # as SSRF/egress blocks: honest for the model, invisible to the breaker.
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    denial = ToolAttempt("a", "file_write", success=False, policy_failure=True)
    c.record([denial, denial, denial])
    assert not c.tool_circuit_breaker()
    assert c.tool_failure_count("file_write") == 0


def test_circuit_breaker_still_counts_real_execution_failures():
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    real = ToolAttempt("a", "file_write", success=False, policy_failure=False)
    c.record([real, real, real])
    cb = c.tool_circuit_breaker()
    # Write tools stay enabled — force segmented instead of circuit-disable.
    assert cb.disabled == ()
    assert "file_write" in cb.force_segmented
    assert c.tool_failure_count("file_write") == 3
    msg = cb.message() or ""
    assert "短骨架" in msg or "分段" in msg
    assert "停用" not in msg


def test_circuit_breaker_parse_only_write_tools_force_segmented_not_disable():
    """Parse-only file_write failures must not retire the pen."""
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    parse = ToolAttempt("a", "file_write", success=False, parse_failure=True)
    c.record([parse])
    assert not c.tool_circuit_breaker()
    c.record([ToolAttempt("b", "file_write", success=False, parse_failure=True)])
    warn = c.tool_circuit_breaker()
    assert warn.warned == ("file_write",)
    assert "file_write" in warn.parse_only
    warn_msg = warn.message() or ""
    assert "分段" in warn_msg or "短骨架" in warn_msg
    assert "原样重发全部参数" not in warn_msg
    c.record([ToolAttempt("c", "file_write", success=False, parse_failure=True)])
    disable = c.tool_circuit_breaker()
    assert disable.disabled == ()
    assert "file_write" in disable.force_segmented
    assert "停用" not in (disable.message() or "")
    assert "原样重发" not in (disable.message() or "")


def test_retire_tools_hard_disables_family_on_first_failure():
    """Permanent capability fail (browser egress): one shot retires the whole family."""
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    family = (
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_snapshot",
        "browser_screenshot",
    )
    steer = "browser_* 因沙箱出网能力不可用已全部停用"
    c.record(
        [
            ToolAttempt(
                "a",
                "browser_navigate",
                success=False,
                error_summary="egress_unavailable",
                meta={
                    "code": "egress_unavailable",
                    "retire_tools": list(family),
                    "retire_message": steer,
                },
            )
        ]
    )
    cb = c.tool_circuit_breaker()
    assert set(cb.disabled) == set(family)
    assert cb.warned == ()
    assert cb.retire_message == steer
    msg = cb.message()
    assert msg is not None and steer in msg
    assert "已多次失败" not in msg
    # Idempotent: further failures do not re-fire.
    c.record(
        [
            ToolAttempt(
                "b",
                "browser_navigate",
                success=False,
                meta={"retire_tools": list(family), "retire_message": steer},
            )
        ]
    )
    assert not c.tool_circuit_breaker()


def test_retire_tools_honored_even_with_contract_failure():
    """file_read same-path tip is contract_failure but must still hard-stop via retire."""
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    steer = "file_read 因同路径触顶已停用：请基于已有正文写作"
    c.record(
        [
            ToolAttempt(
                "tip",
                "file_read",
                success=False,
                error_summary="已多次读取",
                contract_failure=True,
                meta={"retire_tools": ["file_read"], "retire_message": steer},
            )
        ]
    )
    # Without retire honor, contract_failure would leave failures at 0.
    assert c.tool_failure_count("file_read") >= 3
    cb = c.tool_circuit_breaker()
    assert cb.disabled == ("file_read",)
    assert cb.retire_message == steer
    assert "基于已有正文" in (cb.message() or "")


def test_circuit_breaker_ignores_contract_failures_in_one_round():
    # 参数契约拒绝 (web_search A3 query 过长/过多) 是零成本可修正的参数打回：一个研究员
    # 同轮扇出 5 条超长查询也不该烧穿断路器，否则模型还没看到「改 2–4 个核心词重试」的
    # 提示就永久失去 web_search。5 > disable(3)，若计数早已 disable。
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    rej = ToolAttempt("a", "web_search", success=False, contract_failure=True)
    c.record([rej, rej, rej, rej, rej])
    assert not c.tool_circuit_breaker()
    assert c.tool_failure_count("web_search") == 0


def test_circuit_breaker_contract_failures_across_rounds_still_ignored():
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    for fp in ("a", "b", "c", "d"):
        c.record([ToolAttempt(fp, "web_search", success=False, contract_failure=True)])
        assert not c.tool_circuit_breaker()
    assert c.tool_failure_count("web_search") == 0


def test_circuit_breaker_counts_only_real_failures_when_mixed_with_contract():
    # 契约拒绝与真实失败（网络错误等）混合时：只有真实失败计入 warn/disable。
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    rej = ToolAttempt("a", "web_search", success=False, contract_failure=True)
    real = ToolAttempt("b", "web_search", success=False)
    # 3 契约拒绝 + 2 真实失败 → 只数到 2 → warn，不 disable。
    c.record([rej, real, rej, real, rej])
    cb = c.tool_circuit_breaker()
    assert cb.warned == ("web_search",)
    assert cb.disabled == ()
    assert c.tool_failure_count("web_search") == 2
    # 第 3 个真实失败才 disable；夹带的契约拒绝仍不计数。
    c.record([rej, real, rej])
    cb2 = c.tool_circuit_breaker()
    assert cb2.disabled == ("web_search",)
    assert c.tool_failure_count("web_search") == 3


def test_contract_failure_still_counts_as_round_failure_for_detection():
    # 「该轮失败」语义不变：契约拒绝仍进滑窗，同指纹重复≥阈值照常触发 REPEATED_FAILURE。
    c = LoopController(window=8, threshold=3)
    rej = ToolAttempt("same", "web_search", success=False, contract_failure=True)
    c.record([rej, rej, rej])
    signal = c.detect()
    assert signal is not None
    assert signal.reason is StuckReason.REPEATED_FAILURE
    assert signal.tool_name == "web_search"


def test_circuit_breaker_tally_survives_nudge_window_clear():
    # The cumulative per-tool tally is run-scoped: the nudge's sliding-window reset
    # must NOT reset it (otherwise a tool failing across a nudge would never trip).
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    c.record([_fail("a", "t"), _fail("a", "t"), _fail("a", "t")])  # 3 failures
    assert c.decide(c.detect()) is Intervention.NUDGE  # clears the window
    cb = c.tool_circuit_breaker()
    assert cb.disabled == ("t",)


def test_circuit_breaker_parse_failures_get_typed_warn_message():
    """Parse failures still trip warn@2; orchestration stays enabled at disable threshold."""
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    parse = ToolAttempt("a", "delegate", success=False, parse_failure=True)
    c.record([parse])
    assert not c.tool_circuit_breaker()
    c.record([ToolAttempt("b", "delegate", success=False, parse_failure=True)])
    cb = c.tool_circuit_breaker()
    assert cb.warned == ("delegate",)
    assert "delegate" in cb.parse_only
    msg = cb.message() or ""
    assert "不是合法 JSON" in msg
    assert "XML" in msg or "parameter" in msg or "合法 JSON" in msg
    assert "换不同的输入" not in msg
    # Parse-only: keep dispatcher (do not circuit-disable delegate).
    c.record([ToolAttempt("c", "delegate", success=False, parse_failure=True)])
    cb2 = c.tool_circuit_breaker()
    assert cb2.disabled == ()
    assert "停用" not in (cb2.message() or "")
    assert c.tool_failure_count("delegate") == 3


def test_circuit_breaker_orchestration_still_disables_on_real_failures():
    """Mixed / non-parse failures still retire delegate at disable threshold."""
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    real = ToolAttempt("a", "delegate", success=False, parse_failure=False)
    c.record([real, real, real])
    cb = c.tool_circuit_breaker()
    assert cb.disabled == ("delegate",)


def test_circuit_breaker_mixed_failures_keep_generic_warn():
    """If any non-parse failure contributed, keep the generic「换不同的输入」steer."""
    c = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    c.record([ToolAttempt("a", "delegate", success=False, parse_failure=True)])
    c.record([ToolAttempt("b", "delegate", success=False, parse_failure=False)])
    cb = c.tool_circuit_breaker()
    assert cb.warned == ("delegate",)
    assert "delegate" not in cb.parse_only
    assert "换不同的输入" in (cb.message() or "")


# --- B2: no-output early stop (unproductive rounds) ---


def _unproductive(c: LoopController) -> None:
    c.note_round_productivity(had_tool_calls=True, all_failed=True, had_content=False)


def test_unproductive_streak_trips_after_threshold():
    c = LoopController(unproductive_threshold=3)
    _unproductive(c)
    assert not c.unproductive_early_stop()
    _unproductive(c)
    assert not c.unproductive_early_stop()
    _unproductive(c)
    assert c.unproductive_early_stop()


def test_unproductive_streak_resets_on_content():
    c = LoopController(unproductive_threshold=2)
    _unproductive(c)
    # content this round (even with a failing tool) is progress → resets
    c.note_round_productivity(had_tool_calls=True, all_failed=True, had_content=True)
    _unproductive(c)
    assert not c.unproductive_early_stop()  # streak restarted at 1


def test_unproductive_streak_resets_on_tool_success():
    c = LoopController(unproductive_threshold=2)
    _unproductive(c)
    # a tool succeeded → not all-failed → resets
    c.note_round_productivity(had_tool_calls=True, all_failed=False, had_content=False)
    _unproductive(c)
    assert not c.unproductive_early_stop()


def test_no_tool_round_is_not_unproductive():
    # A no-tool round is the empty/degraded path, not the unproductive one.
    c = LoopController(unproductive_threshold=1)
    c.note_round_productivity(had_tool_calls=False, all_failed=False, had_content=False)
    assert not c.unproductive_early_stop()


def test_parse_failure_only_rounds_do_not_count_unproductive():
    """纯协议失败轮不计入 unproductive streak。"""
    c = LoopController(unproductive_threshold=2)
    c.note_round_productivity(
        had_tool_calls=True,
        all_failed=True,
        had_content=False,
        all_parse_failures=True,
    )
    c.note_round_productivity(
        had_tool_calls=True,
        all_failed=True,
        had_content=False,
        all_parse_failures=True,
    )
    assert not c.unproductive_early_stop()
    # 执行失败仍计
    _unproductive(c)
    assert not c.unproductive_early_stop()
    _unproductive(c)
    assert c.unproductive_early_stop()


# --- B2: periodic reflection injection ---


def test_reflection_due_fires_on_cadence():
    c = LoopController(reflection_start_round=3, reflection_interval=3)
    # 4th / 7th / 10th round (0-indexed 3 / 6 / 9) — cadence alone, no latch yet
    assert [r for r in range(11) if c.reflection_due(r)] == [3, 6, 9]


def test_reflection_latches_one_per_idle_streak():
    """Soft 进度复盘每空转段一次；再空转交给 zero_write/convergence，不重复同文案。"""
    c = LoopController(reflection_start_round=3, reflection_interval=3)
    assert c.reflection_due(3)
    c.mark_reflection_injected()
    assert not c.reflection_due(6)
    assert not c.reflection_due(9)
    # Progress clears the latch → cadence can fire again.
    c.record([_ok("w", "file_write")])
    c.record([_ok("r", "web_search")])
    c.record([_ok("r2", "web_search")])
    assert not c.has_recent_progress()
    assert c.reflection_due(9)


def test_reflection_not_due_before_start_round():
    c = LoopController(reflection_start_round=3, reflection_interval=3)
    assert not any(c.reflection_due(r) for r in range(3))


def test_reflection_cadence_is_configurable():
    c = LoopController(reflection_start_round=2, reflection_interval=4)
    assert [r for r in range(11) if c.reflection_due(r)] == [2, 6, 10]


def test_progress_review_prompt_is_anchored_to_round():
    msg = progress_review_prompt(4)
    assert "进度复盘" in msg
    assert "已进行 4 轮" in msg


def test_progress_review_prompt_role_split():
    captain = progress_review_prompt(4, role="captain")
    worker = progress_review_prompt(4, role="worker")
    default = progress_review_prompt(4)

    assert "对照用户目标" in captain
    assert "再委派" in captain or "委派" in captain
    assert "收尾" in captain
    assert "直接给最终答案" not in captain
    assert "直接给出最终答案" not in captain

    assert "落盘" in worker
    assert "handoff" in worker
    assert "禁止直接给最终答案" in worker
    assert "file_read" in worker
    # Default (no role / empty) uses worker copy — solo & leaf workers.
    assert "handoff" in default
    assert "禁止直接给最终答案" in default
    assert captain != worker


def test_progress_review_prompt_form_prose_no_str_replace():
    """D3: prose workers must not be urged to str_replace / file_write."""
    msg = progress_review_prompt(4, form_prose=True)
    assert "form=prose" in msg or "仅文字" in msg
    assert "handoff" in msg
    assert "escalate" in msg
    assert "请用 str_replace" not in msg
    assert "下一步用写文件 / str_replace" not in msg
    # Mentions withheld write tools as forbidden empty spin, not as required action.
    assert "禁止空转调用 str_replace" in msg or "未授" in msg


def test_reflection_skips_when_recent_progress():
    c = LoopController(reflection_start_round=3, reflection_interval=3)
    # Cadence round with a successful file_write → skip.
    c.record([_ok("w", "file_write")])
    assert c.has_recent_progress()
    assert not c.reflection_due(3)

    # Next non-progress round still within「近轮」window → still skip.
    c.record([_ok("r", "web_search")])
    assert c.has_recent_progress()
    assert not c.reflection_due(6)

    # Two non-progress rounds later → cadence may fire again.
    c.record([_ok("r2", "web_search")])
    assert not c.has_recent_progress()
    assert c.reflection_due(6)


def test_file_append_counts_as_progress_for_reflection_skip():
    c = LoopController(reflection_start_round=3, reflection_interval=3)
    c.record([_ok("a", "file_append")])
    assert c.has_recent_progress()
    assert not c.reflection_due(3)


def test_failed_progress_tool_does_not_skip_reflection():
    c = LoopController(reflection_start_round=3, reflection_interval=3)
    c.record([_fail("w", "file_write")])
    assert not c.has_recent_progress()
    assert c.reflection_due(3)


def test_progress_tools_include_append_and_handoff():
    from agentcore.runtime.loop_controller import PROGRESS_TOOLS

    assert {
        "file_write",
        "file_append",
        "str_replace",
        "write_section",
        "handoff",
        "delegate",
        "ask_user",
    } <= PROGRESS_TOOLS


# --- over-investigation safety net (收敛治理, 保险丝: finalize-only runaway backstop) ---
#
# The soft nudge that once lived here was removed: a 3-sample A/B showed it was ignored
# AND net-negative (cost ↑, no call reduction). Routine convergence now lives in the
# system prompt + the read_url failure guidance; this knob only force-finalizes a TRUE
# runaway past a HIGH bar, keyed on investigation *rounds* (a parallel batch counts once).


def _worker(finalize_rounds: int = 6) -> LoopController:
    # A run whose read-only investigation tools advance the safety-net clock. Flavor /
    # delegation no longer matter — the backstop is flavor-agnostic.
    return LoopController(
        convergence_finalize_rounds=finalize_rounds,
        investigation_tools=frozenset({"web_search", "read_url", "file_read"}),
    )


def test_safety_net_disabled_by_default():
    # The plain controller (finalize_rounds 0) never intervenes, however much it searches —
    # rounds are still tracked, but the net stays dormant.
    c = LoopController(investigation_tools=frozenset({"web_search"}))
    for i in range(20):
        c.record([_ok(f"s{i}", "web_search")])
    assert c.investigation_rounds == 20
    assert c.convergence_action() is Intervention.CONTINUE


def test_safety_net_counts_rounds_not_calls_so_a_batch_is_one():
    # THE batch-robustness invariant: a parallel fan-out of N reads in ONE round bumps
    # the clock by one, so a worker can't be guillotined right after fanning out wide.
    c = _worker(finalize_rounds=6)
    c.record(
        [
            _ok("a", "web_search"),
            _ok("b", "web_search"),
            _ok("c", "web_search"),
            _ok("d", "web_search"),
        ]
    )  # batch of 4 → still 1 investigation round
    assert c.investigation_calls == 4
    assert c.investigation_rounds == 1
    assert c.convergence_action() is Intervention.CONTINUE  # 1 ≪ 6


def test_safety_net_continues_below_the_bar_no_soft_nudge():
    # Below the high bar there is NO intervention at all (the old soft NUDGE is gone):
    # every round under finalize_rounds is a plain CONTINUE.
    c = _worker(finalize_rounds=6)
    for i in range(5):  # rounds 1..5, all below 6
        c.record([_ok(f"s{i}", "web_search")])
        assert c.convergence_action() is Intervention.CONTINUE
    assert c.investigation_rounds == 5


def test_safety_net_finalizes_a_true_runaway_at_the_bar():
    c = _worker(finalize_rounds=6)
    for i in range(5):
        c.record([_ok(f"s{i}", "web_search")])
    assert c.convergence_action() is Intervention.CONTINUE  # round 5 < 6
    c.record([_ok("s5", "web_search")])  # round 6 ≥ 6
    assert c.investigation_rounds == 6
    assert c.convergence_action() is Intervention.FINALIZE


def test_safety_net_is_flavor_agnostic():
    # A run that ALSO has an orchestration tool is reined in by the SAME backstop — the
    # old leaf-only convergence let such a worker run to the cap (17 rounds observed).
    c = LoopController(
        convergence_finalize_rounds=6,
        investigation_tools=frozenset({"file_read", "grep"}),
    )
    for i in range(6):
        c.record([_ok(f"r{i}", "file_read")])
    assert c.investigation_rounds == 6
    assert c.convergence_action() is Intervention.FINALIZE


def test_safety_net_ignores_non_investigation_tools():
    # Only read-only investigation tools advance the clock — a worker writing files /
    # asking the user / consulting a skill is making progress, not over-investigating.
    c = _worker(finalize_rounds=6)
    c.record([_ok("a", "file_write"), _ok("b", "ask_user")])
    c.record([_ok("c", "consult_skill")])
    assert c.investigation_rounds == 0
    assert c.convergence_action() is Intervention.CONTINUE


def test_safety_net_round_clock_survives_nudge_window_clear():
    # The investigation-round clock is run-scoped (like the failure tally): a stuck-loop
    # NUDGE clears the sliding window but must NOT reset the safety-net clock.
    c = _worker(finalize_rounds=6)
    c.record([_ok("a", "web_search"), _ok("a", "web_search"), _ok("a", "web_search")])
    assert c.decide(c.detect()) is Intervention.NUDGE  # clears the window
    assert c.investigation_rounds == 1  # survived the clear
    c.record([_ok("b", "read_url")])  # 2nd round, different target
    assert c.investigation_rounds == 2
    assert c.convergence_action() is Intervention.CONTINUE  # still ≪ 6


def test_spinning_same_target_triggers_finalize_before_absolute_cap():
    c = LoopController(
        convergence_finalize_rounds=30,
        convergence_spin_rounds=3,
        investigation_tools=frozenset({"file_read"}),
    )
    fp = "same"
    for _ in range(3):
        c.record([ToolAttempt(fingerprint=fp, tool_name="file_read", success=True)])
        assert c.convergence_action() is Intervention.CONTINUE
    c.record([ToolAttempt(fingerprint=fp, tool_name="file_read", success=True)])
    assert c.convergence_action() is Intervention.FINALIZE


def test_different_investigation_targets_do_not_spin():
    c = LoopController(
        convergence_finalize_rounds=30,
        convergence_spin_rounds=3,
        investigation_tools=frozenset({"file_read"}),
    )
    for i in range(10):
        c.record([ToolAttempt(fingerprint=f"f{i}", tool_name="file_read", success=True)])
        assert c.convergence_action() is Intervention.CONTINUE


def test_progress_tool_resets_spin_streak():
    c = LoopController(
        convergence_finalize_rounds=30,
        convergence_spin_rounds=2,
        investigation_tools=frozenset({"file_read"}),
    )
    c.record([ToolAttempt(fingerprint="same", tool_name="file_read", success=True)])
    c.record([ToolAttempt(fingerprint="same", tool_name="file_read", success=True)])
    assert c.same_target_investigation_streak == 1
    c.record([ToolAttempt(fingerprint="d1", tool_name="delegate", success=True)])
    assert c.same_target_investigation_streak == 0
    assert c.convergence_action() is Intervention.CONTINUE


# --- zero-write thrashing (files-expected investigation idle) ---


def _files_worker(*, zero_write: int = 7, finalize: int = 30) -> LoopController:
    return LoopController(
        convergence_finalize_rounds=finalize,
        convergence_spin_rounds=0,  # isolate zero-write from same-target spin
        zero_write_finalize_rounds=zero_write,
        investigation_tools=frozenset({"file_read", "file_list", "grep"}),
    )


def test_zero_write_finalizes_before_max_rounds():
    c = _files_worker(zero_write=7)
    for i in range(6):
        c.record([ToolAttempt(fingerprint=f"f{i}", tool_name="file_read", success=True)])
        assert c.convergence_action() is Intervention.CONTINUE
    assert c.zero_write_warn_due()
    c.record([ToolAttempt(fingerprint="f6", tool_name="file_read", success=True)])
    assert c.zero_write_investigation_rounds == 7
    assert c.convergence_action() is Intervention.FINALIZE
    assert c.is_thrashing()


def test_zero_write_disabled_without_threshold():
    c = LoopController(
        convergence_finalize_rounds=30,
        convergence_spin_rounds=0,
        zero_write_finalize_rounds=0,
        investigation_tools=frozenset({"file_read"}),
    )
    for i in range(12):
        c.record([ToolAttempt(fingerprint=f"f{i}", tool_name="file_read", success=True)])
    assert c.convergence_action() is Intervention.CONTINUE
    assert not c.is_thrashing()


def test_govern_after_tools_zero_write_finalize_is_degraded():
    """Mid-loop zero_write FINALIZE stamps DEGRADED (aligned with ceiling)."""
    from agentcore.runtime.engine.directive import Finalize
    from agentcore.runtime.engine.governance import govern_after_tools
    from agentcore.runtime.engine.outcome import RoundOutcome
    from agentcore.runtime.events import FinishReason

    c = _files_worker(zero_write=3)
    for i in range(3):
        c.record([ToolAttempt(fingerprint=f"f{i}", tool_name="file_read", success=True)])
    messages: list = []
    directive = govern_after_tools(
        RoundOutcome(
            content="",
            reasoning="",
            usage=None,
            tool_calls=[],
            tool_results=[],
            attempts=[],
        ),
        c,
        messages=messages,
        round_idx=3,
        run_id="r1",
        breaker_message=None,
    )
    assert isinstance(directive, Finalize)
    assert directive.reason == "convergence"
    assert directive.finish_reason is FinishReason.DEGRADED


def test_landing_success_resets_zero_write_streak():
    c = _files_worker(zero_write=4)
    for i in range(3):
        c.record([ToolAttempt(fingerprint=f"f{i}", tool_name="file_read", success=True)])
    assert c.zero_write_investigation_rounds == 3
    c.record([ToolAttempt(fingerprint="w", tool_name="str_replace", success=True)])
    assert c.landing_succeeded
    assert c.zero_write_investigation_rounds == 0
    for i in range(3):
        c.record([ToolAttempt(fingerprint=f"g{i}", tool_name="file_read", success=True)])
    assert c.convergence_action() is Intervention.CONTINUE  # streak irrelevant after land


def test_landing_attempt_exempts_round_from_zero_write():
    """Failed write is 落盘意图 — does not bump the idle clock."""
    c = _files_worker(zero_write=3)
    c.record([ToolAttempt(fingerprint="a", tool_name="file_read", success=True)])
    c.record([ToolAttempt(fingerprint="b", tool_name="file_read", success=True)])
    c.record(
        [
            ToolAttempt(fingerprint="r", tool_name="file_read", success=True),
            ToolAttempt(fingerprint="w", tool_name="str_replace", success=False),
        ]
    )
    assert c.zero_write_investigation_rounds == 0
    assert c.convergence_action() is Intervention.CONTINUE


def test_different_targets_still_trip_zero_write():
    """换文件通读不算 spin，但仍算零写空转。"""
    c = _files_worker(zero_write=5, finalize=30)
    for i in range(5):
        c.record([ToolAttempt(fingerprint=f"path{i}", tool_name="file_read", success=True)])
    assert c.same_target_investigation_streak == 0
    assert c.convergence_action() is Intervention.FINALIZE
    assert c.is_thrashing()


def _prose_worker(*, idle: int = 3, finalize: int = 30) -> LoopController:
    return LoopController(
        convergence_finalize_rounds=finalize,
        convergence_spin_rounds=0,
        zero_write_finalize_rounds=idle,
        prose_idle=True,
        investigation_tools=frozenset({"file_read", "grep", "code_search"}),
    )


def test_prose_idle_finalizes_and_handoff_counts_as_delivery():
    c = _prose_worker(idle=3)
    for i in range(2):
        c.record([ToolAttempt(fingerprint=f"f{i}", tool_name="file_read", success=True)])
        assert c.convergence_action() is Intervention.CONTINUE
    assert c.zero_write_warn_due()
    c.record([ToolAttempt(fingerprint="f2", tool_name="file_read", success=True)])
    assert c.convergence_action() is Intervention.FINALIZE

    c2 = _prose_worker(idle=3)
    c2.record([ToolAttempt(fingerprint="a", tool_name="file_read", success=True)])
    c2.record([ToolAttempt(fingerprint="b", tool_name="file_read", success=True)])
    c2.record([ToolAttempt(fingerprint="h", tool_name="handoff", success=True)])
    assert c2.landing_succeeded
    assert c2.zero_write_investigation_rounds == 0
    assert c2.convergence_action() is Intervention.CONTINUE


def test_prose_idle_warn_prompt_mentions_prose_not_landing():
    from agentcore.runtime.loop_controller import (
        zero_write_finalize_prompt,
        zero_write_warn_prompt,
    )

    warn = zero_write_warn_prompt(rounds=2, prose_idle=True)
    assert "散文" in warn or "诊断" in warn
    assert "str_replace" not in warn
    fin = zero_write_finalize_prompt(rounds=3, prose_idle=True)
    assert "散文" in fin or "根因" in fin
