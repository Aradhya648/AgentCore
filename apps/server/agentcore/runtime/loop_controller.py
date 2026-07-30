"""Convergence governance: deterministic stuck detection + graded intervention.

This runs *outside* the model — no extra LLM calls — between ReAct rounds. It
catches the three canonical mechanical loop patterns that a model does not
recognize about itself, over a sliding window of recent tool attempts:

  * repeated identical tool call  — same tool + same normalized args
  * A-B-A-B alternation           — oscillating between two calls
  * repeated identical failure    — same tool failing the same way

When a pattern trips, the controller recommends a *graded* intervention: first a
nudge (a reflection message anchored to the concrete detected fact, never
open-ended self-doubt), then a hard finalize (force a tool-free answer).

Design grounding (see 规划/收敛治理-loop_controller.md): hard round caps are a
tripwire, not a convergence mechanism; detection must be enforced in code, not
via prompt; and an injected reflection must be anchored to an external signal
(the observed repetition) or it diverges into self-flagellation / sycophancy.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

DEFAULT_WINDOW = 8
DEFAULT_THRESHOLD = 3
# Consecutive empty-response rounds that trip a degraded finish (B2). The fallback
# retry sits inside this streak, so the default 2 = one empty → fallback retry → if
# still empty, degraded.
DEFAULT_EMPTY_THRESHOLD = 2
# Tool failure circuit breaker (B2): cumulative (run-scoped, args-agnostic) failure
# counts per tool. At the warn threshold the model is told to stop retrying that
# tool; at the disable threshold the tool is removed from the toolset for the rest
# of the run. Unlike REPEATED_FAILURE detection (which keys on the exact call
# fingerprint within the sliding window), this counts a tool failing *any* way and
# never resets — it catches "this tool just isn't working out, no matter the args".
DEFAULT_TOOL_FAILURE_WARN = 2
DEFAULT_TOOL_FAILURE_DISABLE = 3
# Consecutive *unproductive* rounds that trip an early stop (B2 无产出早停). An
# unproductive round = the model called ≥1 tool, every call FAILED, and it produced
# no content — it is "working" but getting nowhere. Distinct from an empty round
# (no tool call at all → degraded ladder).
DEFAULT_UNPRODUCTIVE_THRESHOLD = 3
# Periodic progress-review reflection (B2 反思注入): on a long multi-round run, inject
# a "step back and re-plan" prompt starting at the 4th round (0-indexed 3) and every
# 3 rounds after (rounds 4 / 7 / 10 …). Cadence-driven and proactive — unlike the
# event-driven NUDGE, which only fires once a mechanical loop is detected.
DEFAULT_REFLECTION_START_ROUND = 3
DEFAULT_REFLECTION_INTERVAL = 3
# Progress tools that reset investigation spinning and suppress periodic reflection
# when a recent round succeeded (stage advance / delivery / handoff / ask).
# ``str_replace`` / ``write_section`` count: coding repair lands via patch, not only
# whole-file write.
PROGRESS_TOOLS = frozenset(
    {
        "delegate",
        "file_write",
        "file_append",
        "str_replace",
        "write_section",
        "handoff",
        "ask_user",
    }
)
# Workspace landing tools: success clears zero-write thrashing; any attempt is
# "落盘意图" and exempts that round from the zero-write clock.
LANDING_TOOLS = frozenset(
    {"file_write", "file_append", "str_replace", "write_section", "file_move"}
)


def zero_write_warn_prompt(*, rounds: int, prose_idle: bool = False) -> str:
    """Hard steer before idle FINALIZE (files zero-write or prose short idle)."""
    if prose_idle:
        return (
            f"[系统提示] 只读不交卷告警（已连续 {rounds} 轮仅调查、无散文交付）："
            "请立即基于已读内容写出短诊断/验证结论（或 handoff 交接），"
            "禁止继续换文件通读空转。下一轮仍无正文将强制收口。"
        )
    return (
        f"[系统提示] 只读空转告警（已连续 {rounds} 轮仅调查、零落盘）："
        "任务要求写盘交付。请立即 str_replace / file_write 落地，或 handoff 诚实说明阻塞；"
        "禁止继续换文件通读空转。下一轮仍无落盘将强制收口。"
    )


def zero_write_finalize_prompt(*, rounds: int, prose_idle: bool = False) -> str:
    """Injected on idle FINALIZE so salvage answers name the idle pattern."""
    if prose_idle:
        return (
            f"[系统提示] 只读不交卷强制收口（连续 {rounds} 轮调查且无散文交付）："
            "请基于已读内容写出根因/结论并 handoff，勿再展开新调研。"
        )
    return (
        f"[系统提示] 只读空转强制收口（连续 {rounds} 轮调查且零落盘）："
        "请基于已读内容交接当前缺口，勿再展开新调研。"
    )


def progress_review_prompt(
    round_number: int, *, role: str = "", form_prose: bool = False
) -> str:
    """The periodic progress-review steer (B2 反思注入), anchored to the round count.

    Role-split copy: captain/CEO aligns to the user goal and chooses 派/问/收尾;
    workers confirm deliverable landing and either fix files or same-round handoff.
    ``form_prose`` workers must not be told to ``str_replace`` / ``file_write``.
    Never open-ended self-doubt; never push workers toward「最终答案」or self-readback.
    """
    if role == "captain":
        return (
            f"[系统提示] 进度复盘（已进行 {round_number} 轮）：请对照用户目标梳理——"
            "(1) 目前已确认了哪些关键事实？(2) 距离用户的目标还差什么？"
            "(3) 下一步是再委派、向用户提问，还是基于已有产出收尾？"
            "避免重复已经做过的尝试；不要为复盘去 file_read 产物正文。"
        )
    if form_prose:
        return (
            f"[系统提示] 进度复盘（已进行 {round_number} 轮）：请停下来确认——"
            "(1) 本回合是 form=prose（仅文字报告），交付是否已写完正文？"
            "(2) 若未写完：继续写正文后 handoff；若任务实际需要改文件，请 escalate "
            "请主管改 form=files 后重派，或 handoff 诚实说明形态阻塞——"
            "禁止空转调用 str_replace / file_write（本回合未授）。"
            "(3) 若已满足：请在本轮调用 handoff 交接，不要再展开新调研。"
            "禁止直接给最终答案代替交接；禁止为复盘去 file_read 自己刚写的产物。"
        )
    return (
        f"[系统提示] 进度复盘（已进行 {round_number} 轮）：请停下来确认——"
        "(1) 你的交付是否已按合同落盘（或 prose 正文已写完）？"
        "(2) 若未满足：下一步用写文件 / str_replace 等具体改法补齐，不要空转；"
        "(3) 若已满足：请在本轮调用 handoff 交接，不要再展开新调研。"
        "禁止直接给最终答案代替交接；禁止为复盘去 file_read 自己刚写的产物。"
    )


class StuckReason(StrEnum):
    """Which mechanical loop pattern was observed."""

    REPEATED_CALL = "repeated_call"
    ALTERNATING = "alternating"
    REPEATED_FAILURE = "repeated_failure"


class Intervention(StrEnum):
    """What the engine should do this round."""

    CONTINUE = "continue"
    NUDGE = "nudge"
    FINALIZE = "finalize"


@dataclass(frozen=True)
class ToolAttempt:
    """One executed tool call in a round; ``success`` carries the failure signal."""

    fingerprint: str
    tool_name: str
    success: bool
    # Policy/environment/governance blocks (SSRF, egress breaker, approval denial) are
    # honest tool failures for the model but must not trip the run-scoped circuit
    # breaker — the tool itself is fine; the call was refused upstream.
    policy_failure: bool = False
    # Arguments string failed ``json.loads`` before the tool ran — still counts toward
    # the run-scoped breaker, but steers must not say「换不同的输入」(that pushes the
    # model to shorten/rewrite a DAG that only needed quote-escaping).
    parse_failure: bool = False
    # 参数契约拒绝: a deterministic argument-contract rejection (e.g. web_search A3 query
    # 过长/过多) whose error already tells the model exactly how to fix it. Like
    # ``policy_failure`` it is invisible to the run-scoped circuit breaker — a same-round
    # fan-out of over-long queries must not burn the disable threshold before the model can
    # act on the fix tip — but unlike it, this names a self-correctable参数打回, not an
    # upstream block. It still lands in the sliding window as an honest failure, so
    # REPEATED_FAILURE detection, unproductive early-stop, and round recording are unchanged;
    # only the cumulative warn/disable tally (``_tool_failures``) skips it.
    contract_failure: bool = False
    # Short error text for honest finalize / CEO synthesis (ignored on success /
    # policy_failure). Capped when recorded on the controller.
    error_summary: str = ""
    # Optional tool-result metadata forwarded for governance (e.g. delegate batch shape).
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StuckSignal:
    """A detected stuck pattern plus the facts needed to anchor a nudge."""

    reason: StuckReason
    tool_name: str
    count: int

    def reflection_message(self) -> str:
        """Steer message anchored to the concrete observation.

        Anchoring to the real fact ("you called X 3 times") rather than a vague
        "think harder" is what keeps the injected reflection from diverging.
        """
        if self.reason is StuckReason.REPEATED_FAILURE:
            return (
                f"[系统提示] 工具 `{self.tool_name}` 已用相同方式失败 {self.count} 次，"
                "继续重试只会再次失败。请不要再以相同参数调用它："
                "改用不同的输入、换一个工具，或基于已有信息直接给出最终答案。"
            )
        if self.reason is StuckReason.ALTERNATING:
            return (
                f"[系统提示] 你在两个动作之间来回循环（其中之一是 `{self.tool_name}`）"
                "却没有取得进展。请跳出循环：选定一个能真正推进到答案的具体下一步，"
                "或现在就给出最终答案。"
            )
        return (
            f"[系统提示] 你已用相同参数调用 `{self.tool_name}` {self.count} 次，"
            "没有任何新进展。请停止重复：要么换一种实质不同的做法或参数，"
            "要么基于现有信息直接给出最终答案。"
        )


@dataclass(frozen=True)
class CircuitBreak:
    """Tools that crossed a cumulative-failure threshold this round (B2 熔断).

    ``warned`` hit the warn threshold (tell the model to stop retrying them);
    ``disabled`` hit the disable threshold (the engine removes them from the
    toolset for the rest of the run). Each is a tuple of tool names; both empty
    means nothing tripped this round.

    ``parse_only`` names tools whose failures so far are *all* argument-JSON parse
    failures — their steer text must guide「修复格式、原样重发」, never「换不同的输入」.

    ``retire_message`` is an optional hard-stop steer (e.g. browser egress
    unavailable) that replaces the generic「已多次失败」disable copy when set.
    """

    warned: tuple[str, ...] = ()
    disabled: tuple[str, ...] = ()
    parse_only: frozenset[str] = frozenset()
    retire_message: str | None = None

    def __bool__(self) -> bool:
        return bool(self.warned or self.disabled)

    def message(self) -> str | None:
        """The single ``[系统提示]`` to inject this round, or ``None``.

        Anchored to the concrete fact (which tool, what now happens) like the
        nudge messages — disable first (the stronger action), then warn.
        Parse-only failures get a typed steer so the model fixes JSON escaping
        instead of rewriting/shortening the payload. ``read_url`` disable/warn
        uses a research-specific stop-read steer (do not say「换不同的输入」—
        that encourages URL thrashing after egress storms).
        """
        parts: list[str] = []
        if self.disabled:
            if self.retire_message:
                parts.append(self.retire_message.strip())
            else:
                parse_d = tuple(n for n in self.disabled if n in self.parse_only)
                other_d = tuple(n for n in self.disabled if n not in self.parse_only)
                read_d = tuple(n for n in other_d if n == "read_url")
                other_d = tuple(n for n in other_d if n != "read_url")
                if read_d:
                    from agentcore.tools.builtin.web._net import READ_URL_RETIRE_STEER

                    parts.append(READ_URL_RETIRE_STEER)
                if other_d:
                    names = "、".join(f"`{n}`" for n in other_d)
                    parts.append(
                        f"工具 {names} 已多次失败，本回合起停用，无法再调用——"
                        "请改用其他工具或基于已有信息推进。"
                    )
                if parse_d:
                    names = "、".join(f"`{n}`" for n in parse_d)
                    parts.append(
                        f"工具 {names} 因参数不是合法 JSON 已多次失败，本回合起停用，无法再调用——"
                        "请改用其他工具或基于已有信息推进。"
                    )
        if self.warned:
            parse_w = tuple(n for n in self.warned if n in self.parse_only)
            other_w = tuple(n for n in self.warned if n not in self.parse_only)
            read_w = tuple(n for n in other_w if n == "read_url")
            other_w = tuple(n for n in other_w if n != "read_url")
            if read_w:
                parts.append(
                    "工具 `read_url` 已多次失败，请不要再换 URL / 同策略空转重读——"
                    "改用已有 web_search 摘要与已读材料推进写作，或换一个非外网读页工具。"
                )
            if other_w:
                names = "、".join(f"`{n}`" for n in other_w)
                parts.append(
                    f"工具 {names} 已多次失败，请不要再以相同方式调用它："
                    "换不同的输入、换一个工具，或基于已有信息直接推进。"
                )
            if parse_w:
                names = "、".join(f"`{n}`" for n in parse_w)
                parts.append(
                    f"工具 {names} 的调用参数不是合法 JSON，已多次解析失败："
                    "请修复 JSON 格式（尤其是字符串内引号转义）后原样重发全部参数，"
                    "不要改写、缩短或删减内容；也可换一个工具或基于已有信息直接推进。"
                )
        if not parts:
            return None
        return "[系统提示] " + " ".join(parts)


def fingerprint_tool_call(name: str, arguments: str) -> str:
    """Stable hash of ``(tool_name, normalized args)``.

    Args are normalized via key-sorted JSON so semantically identical calls map
    to one fingerprint; malformed JSON falls back to the raw argument string so
    verbatim repeats are still caught.
    """
    try:
        parsed = json.loads(arguments) if arguments else {}
        normalized = json.dumps(parsed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        normalized = arguments or ""
    return hashlib.sha1(f"{name}\x00{normalized}".encode()).hexdigest()


class LoopController:
    """Sliding-window stuck detector with a two-strike intervention policy.

    One instance per ReAct run — the window and the "already nudged" flag are
    per-run state and must not be shared across concurrent runs.
    """

    def __init__(
        self,
        *,
        window: int = DEFAULT_WINDOW,
        threshold: int = DEFAULT_THRESHOLD,
        empty_threshold: int = DEFAULT_EMPTY_THRESHOLD,
        tool_failure_warn: int = DEFAULT_TOOL_FAILURE_WARN,
        tool_failure_disable: int = DEFAULT_TOOL_FAILURE_DISABLE,
        unproductive_threshold: int = DEFAULT_UNPRODUCTIVE_THRESHOLD,
        reflection_start_round: int = DEFAULT_REFLECTION_START_ROUND,
        reflection_interval: int = DEFAULT_REFLECTION_INTERVAL,
        convergence_finalize_rounds: int = 0,
        convergence_spin_rounds: int = DEFAULT_THRESHOLD,
        zero_write_finalize_rounds: int = 0,
        prose_idle: bool = False,
        form_prose: bool = False,
        investigation_tools: frozenset[str] = frozenset(),
    ) -> None:
        self._window = window
        self._threshold = threshold
        self._empty_threshold = max(1, empty_threshold)
        self._tool_failure_warn = max(1, tool_failure_warn)
        self._tool_failure_disable = max(self._tool_failure_warn, tool_failure_disable)
        self._unproductive_threshold = max(1, unproductive_threshold)
        self._reflection_start_round = max(0, reflection_start_round)
        self._reflection_interval = max(1, reflection_interval)
        self._recent: deque[ToolAttempt] = deque(maxlen=window)
        self._nudged = False
        self._investigation_tools = investigation_tools
        # ``investigation_calls`` = cumulative read-only calls (run-scoped); ``investigation
        # _rounds`` = rounds with >=1 such call. The over-investigation safety net triggers
        # on ROUNDS, not calls, so a parallel batch (several reads in one round) counts once
        # and can't guillotine a worker after a single fan-out. Both feed the finalize log.
        self._investigation_calls = 0
        self._investigation_rounds = 0
        # Local file peeks only (file_list / file_read / grep) — team_gate local-edit path.
        self._local_recon_calls = 0
        # Over-investigation safety net (收敛治理, 保险丝): absolute round ceiling plus
        # progress-aware spinning on repeated same-target reads. ``finalize_rounds <= 0``
        # disables the absolute cap; ``spin_rounds <= 0`` disables spinning detection.
        self._convergence_finalize_rounds = max(0, convergence_finalize_rounds)
        self._convergence_spin_rounds = max(0, convergence_spin_rounds)
        # Delivery-idle thrashing: investigation-only with no delivery success.
        # Files mode = landing write; prose_idle = handoff (or landing if present).
        # ``<= 0`` disables. Landing/handoff *attempt* resets; success latches done.
        self._zero_write_finalize_rounds = max(0, zero_write_finalize_rounds)
        self._prose_idle = bool(prose_idle)
        self._form_prose = bool(form_prose)
        self._zero_write_investigation_rounds = 0
        self._zero_write_warned = False
        self._landing_succeeded = False
        self._prev_investigation_fps: frozenset[str] = frozenset()
        self._same_target_investigation_streak = 0
        # B2 empty-response sub-policy: a separate consecutive-empty-round counter.
        self._consecutive_empty = 0
        # B2 tool circuit breaker: cumulative per-tool failure counts (run-scoped,
        # never cleared by the nudge window reset) + one-shot latches so each tool
        # fires its warn / disable transition at most once. ``_tool_parse_failures``
        # tracks the parse-only subset so steers can be typed without changing thresholds.
        # ``_tool_last_error`` / ``_tool_succeeded_after_fail`` enrich the same tally for
        # honest finalize injection (not a parallel counter).
        self._tool_failures: Counter[str] = Counter()
        self._tool_parse_failures: Counter[str] = Counter()
        self._tool_last_error: dict[str, str] = {}
        self._tool_succeeded_after_fail: dict[str, bool] = {}
        self._tool_warned: set[str] = set()
        self._tool_disabled: set[str] = set()
        # One-shot hard-stop steer from a tool that retires a family (e.g. browser
        # egress_unavailable). Consumed by :meth:`tool_circuit_breaker`.
        self._pending_retire_message: str | None = None
        # B2 no-output early stop: consecutive unproductive rounds (all tools failed,
        # no content). Reset by any productive round (content OR a tool success).
        self._consecutive_unproductive = 0
        # B2 reflection skip: rounds since a successful PROGRESS_TOOLS call (0 = this
        # round). ``None`` = never had progress. Skip inject when ≤1 (本轮或近轮).
        self._rounds_since_progress: int | None = None
        # One soft 进度复盘 per idle streak; further cadence hits defer to zero_write /
        # convergence instead of re-nagging the same「请落盘/handoff」copy.
        self._reflection_latched_since_progress: bool = False
        # Post-delegate synthesis mode (优化六): after delegate returns, steer the CEO away
        # from repeating investigation work the team already did.
        self._post_delegate: bool = False
        self._post_delegate_investigation_count: int = 0
        # Soft team-gate nudge (协作优先阶段 3): at most once per run, captain-only.
        self._team_gate_fired: bool = False
        # 闸后长文直答再催：每 run 一次。
        self._team_gate_direct_reject_fired: bool = False
        # Soft audit-gate nudge (协作优先阶段 3 返工环): at most once per run, captain-only.
        self._audit_gate_fired: bool = False
        # 成篇硬门：research_report / deliverable 结构信号 — nudge 后仍不可直接 end_turn。
        self._audit_hard_required: bool = False
        self._audit_includes_review: bool = False
        # Soft debate-commitment nudge: user picked a debate form on kickoff; at most once.
        self._debate_gate_fired: bool = False
        self._debate_executed: bool = False
        # Turn-token ceiling wrap-up steer (策略 A Step 2): at most once per run, captain-only.
        self._turn_token_budget_gate_fired: bool = False
        self._delegate_count: int = 0
        self._first_batch_substantial: bool = False

    def mark_post_delegate(
        self,
        *,
        node_count: int = 0,
        has_deps: bool = False,
        audit_hard: bool = False,
        includes_review: bool = False,
    ) -> None:
        """Mark that a delegate call just returned — CEO is now in synthesis mode.

        ``node_count`` / ``has_deps`` describe this batch so the audit gate can tell
        a substantial first batch (nodes ≥3 or any depends_on) from a light one.
        ``audit_hard`` / ``includes_review`` stamp成篇硬门（research_report / 结构字段）.
        """
        self._post_delegate = True
        self._post_delegate_investigation_count = 0
        self._delegate_count += 1
        if self._delegate_count == 1:
            self._first_batch_substantial = node_count >= 3 or has_deps
            if audit_hard:
                self._audit_hard_required = True
            if includes_review:
                self._audit_includes_review = True
        elif includes_review or self._audit_hard_required:
            # 第二批起视为独立审校已派（或再次带审校角色）→ 硬门满足。
            self._audit_includes_review = True

    @property
    def has_delegated(self) -> bool:
        """True once a ``delegate`` call has returned in this run."""
        return self._post_delegate

    @property
    def delegate_count(self) -> int:
        """How many successful ``delegate`` returns this run has seen."""
        return self._delegate_count

    @property
    def first_batch_substantial(self) -> bool:
        """True if the first delegate batch was substantial (nodes ≥3 or has deps)."""
        return self._first_batch_substantial

    @property
    def audit_hard_required(self) -> bool:
        """True when long-form / research_report batches require audit before end_turn."""
        return self._audit_hard_required

    @property
    def audit_includes_review(self) -> bool:
        """True when an independent review wave already ran (playbook or follow-up)."""
        return self._audit_includes_review

    def mark_audit_satisfied(self) -> None:
        """Latch that independent review has been dispatched / included."""
        self._audit_includes_review = True

    @property
    def team_gate_fired(self) -> bool:
        """True after the soft team-gate nudge has been injected (latched)."""
        return self._team_gate_fired

    def mark_team_gate_fired(self) -> None:
        """Latch the one-shot team-gate so it cannot fire again this run."""
        self._team_gate_fired = True

    @property
    def team_gate_direct_reject_fired(self) -> bool:
        """True after the post-gate long-answer reject has fired."""
        return self._team_gate_direct_reject_fired

    def mark_team_gate_direct_reject_fired(self) -> None:
        """Latch the one-shot team-gate direct-answer reject."""
        self._team_gate_direct_reject_fired = True

    @property
    def audit_gate_fired(self) -> bool:
        """True after the soft audit-gate nudge has been injected (latched)."""
        return self._audit_gate_fired

    def mark_audit_gate_fired(self) -> None:
        """Latch the one-shot audit-gate so it cannot fire again this run."""
        self._audit_gate_fired = True

    @property
    def debate_gate_fired(self) -> bool:
        """True after the soft debate-commitment nudge has been injected (latched)."""
        return self._debate_gate_fired

    def mark_debate_gate_fired(self) -> None:
        """Latch the one-shot debate-commitment gate so it cannot fire again this run."""
        self._debate_gate_fired = True

    @property
    def debate_executed(self) -> bool:
        """True once a successful ``debate`` tool return has been noted this run."""
        return self._debate_executed

    def mark_debate_executed(self) -> None:
        """Record that ``debate`` completed successfully (suppresses the commitment nudge)."""
        self._debate_executed = True

    @property
    def turn_token_budget_gate_fired(self) -> bool:
        """True after the turn-token wrap-up steer has been injected (latched)."""
        return self._turn_token_budget_gate_fired

    def mark_turn_token_budget_gate_fired(self) -> None:
        """Latch the one-shot turn-token wrap-up steer so it cannot fire again this run."""
        self._turn_token_budget_gate_fired = True

    def export_seed(self) -> dict[str, bool | int]:
        """JSON-safe snapshot of the cross-suspension latches (turn_paused.controller)."""
        return {
            "post_delegate": self._post_delegate,
            "delegate_count": self._delegate_count,
            "team_gate_fired": self._team_gate_fired,
            "team_gate_direct_reject_fired": self._team_gate_direct_reject_fired,
            "audit_gate_fired": self._audit_gate_fired,
            "first_batch_substantial": self._first_batch_substantial,
            "audit_hard_required": self._audit_hard_required,
            "audit_includes_review": self._audit_includes_review,
            "debate_gate_fired": self._debate_gate_fired,
            "debate_executed": self._debate_executed,
            "turn_token_budget_gate_fired": self._turn_token_budget_gate_fired,
        }

    def apply_seed(self, seed: Mapping[str, Any]) -> None:
        """Restore cross-suspension latches from a prior :meth:`export_seed` snapshot."""
        self._post_delegate = bool(seed.get("post_delegate", False))
        self._delegate_count = int(seed.get("delegate_count", 0) or 0)
        self._team_gate_fired = bool(seed.get("team_gate_fired", False))
        self._team_gate_direct_reject_fired = bool(
            seed.get("team_gate_direct_reject_fired", False)
        )
        self._audit_gate_fired = bool(seed.get("audit_gate_fired", False))
        self._first_batch_substantial = bool(seed.get("first_batch_substantial", False))
        self._audit_hard_required = bool(seed.get("audit_hard_required", False))
        self._audit_includes_review = bool(seed.get("audit_includes_review", False))
        self._debate_gate_fired = bool(seed.get("debate_gate_fired", False))
        self._debate_executed = bool(seed.get("debate_executed", False))
        self._turn_token_budget_gate_fired = bool(
            seed.get("turn_token_budget_gate_fired", False)
        )

    def post_delegate_check(self, tool_names: set[str]) -> str | None:
        """Check if CEO is doing investigation work after delegating.

        Returns a reminder message if needed, None otherwise.
        """
        if not self._post_delegate:
            return None
        investigation_used = tool_names & self._investigation_tools
        if not investigation_used:
            return None
        self._post_delegate_investigation_count += 1
        if self._post_delegate_investigation_count == 1:
            return (
                "[系统提示] 你已将此工作委派给团队。请直接基于团队的产出写综述，"
                "不要重复调查。如需验证某个具体细节可读 worker 产出的文件，"
                "但不要展开新的调研。"
            )
        if self._post_delegate_investigation_count == 2:
            return (
                "[系统提示] 你仍在做已委派给团队的调查工作。请立即停止调研，"
                "基于团队已有产出写综述收尾。"
            )
        return None  # 第三次由 convergence_action 处理

    def record(self, attempts: list[ToolAttempt]) -> None:
        """Append one round's tool attempts (in call order) to the window.

        Also bumps the run-scoped per-tool cumulative failure tally that drives the
        circuit breaker — independent of the sliding window (which the nudge reset
        clears), since "this tool keeps failing" is a whole-run signal.
        """
        round_investigated = False
        round_progress = any(
            attempt.success and attempt.tool_name in PROGRESS_TOOLS for attempt in attempts
        )
        landing_success = any(
            attempt.success and attempt.tool_name in LANDING_TOOLS for attempt in attempts
        )
        landing_attempt = any(attempt.tool_name in LANDING_TOOLS for attempt in attempts)
        handoff_success = any(
            attempt.success and attempt.tool_name == "handoff" for attempt in attempts
        )
        delivery_success = landing_success or (self._prose_idle and handoff_success)
        delivery_attempt = landing_attempt or (
            self._prose_idle and any(a.tool_name == "handoff" for a in attempts)
        )
        if delivery_success:
            self._landing_succeeded = True
            self._zero_write_investigation_rounds = 0
            self._zero_write_warned = False
        if round_progress:
            self._same_target_investigation_streak = 0
            self._prev_investigation_fps = frozenset()
            self._rounds_since_progress = 0
            self._reflection_latched_since_progress = False
        elif self._rounds_since_progress is not None:
            self._rounds_since_progress += 1

        from agentcore.runtime.tool_failures import cap_error_summary

        inv_fps: set[str] = set()
        for attempt in attempts:
            self._recent.append(attempt)
            # ``policy_failure`` (upstream block) and ``contract_failure`` (self-correctable
            # 参数契约拒绝) are honest failures for the model but must not feed the run-scoped
            # circuit breaker: they still ride the sliding window above (REPEATED_FAILURE /
            # round recording) and count toward per-round unproductive detection, only the
            # cumulative warn/disable tally skips them.
            if not attempt.success and not attempt.policy_failure and not attempt.contract_failure:
                name = attempt.tool_name
                self._tool_failures[name] += 1
                if attempt.parse_failure:
                    self._tool_parse_failures[name] += 1
                summary = (attempt.error_summary or "").strip()
                if summary:
                    self._tool_last_error[name] = cap_error_summary(summary)
                # A later failure re-opens the gap until a subsequent success.
                self._tool_succeeded_after_fail[name] = False
            # Explicit hard-stop retire (browser egress / file_read same-path ceiling)
            # must apply even when ``contract_failure`` — otherwise tip thrashing
            # never disables the tool (P2: attachment file_read tip×N).
            if not attempt.success:
                retire = attempt.meta.get("retire_tools") if attempt.meta else None
                if isinstance(retire, (list, tuple, set, frozenset)) and retire:
                    summary = (attempt.error_summary or "").strip()
                    for sibling in retire:
                        sname = str(sibling).strip()
                        if not sname:
                            continue
                        self._tool_failures[sname] = max(
                            int(self._tool_failures.get(sname, 0)),
                            self._tool_failure_disable,
                        )
                        if summary and sname not in self._tool_last_error:
                            self._tool_last_error[sname] = cap_error_summary(summary)
                        self._tool_succeeded_after_fail[sname] = False
                    retire_msg = attempt.meta.get("retire_message") if attempt.meta else None
                    if isinstance(retire_msg, str) and retire_msg.strip():
                        self._pending_retire_message = retire_msg.strip()
            if attempt.success and self._tool_failures.get(attempt.tool_name, 0) > 0:
                self._tool_succeeded_after_fail[attempt.tool_name] = True
            # Over-investigation bookkeeping (收敛治理): tally read-only investigation
            # breadth. Counts every call (incl. failures) — a wide scan is breadth
            # regardless of per-call success.
            if attempt.tool_name in self._investigation_tools:
                self._investigation_calls += 1
                round_investigated = True
                inv_fps.add(attempt.fingerprint)
                if attempt.tool_name in {"file_list", "file_read", "grep"}:
                    self._local_recon_calls += 1
        # Rounds, not raw calls, drive the safety net: a parallel batch of N reads in one
        # round bumps this once, so fanning out can't guillotine the worker.
        if round_investigated:
            self._investigation_rounds += 1
            if not round_progress:
                current = frozenset(inv_fps)
                if (
                    current
                    and self._prev_investigation_fps
                    and current <= self._prev_investigation_fps
                ):
                    self._same_target_investigation_streak += 1
                else:
                    self._same_target_investigation_streak = 0
                self._prev_investigation_fps = current

        # Delivery-idle thrashing (files zero-write / prose short idle): investigation-only
        # round with no delivery attempt bumps the streak; delivery intent/success resets.
        # Non-investigation rounds (ask / progress / exec) clear the idle clock.
        if self._zero_write_finalize_rounds > 0 and not self._landing_succeeded:
            tool_names = {a.tool_name for a in attempts if a.tool_name}
            investigation_only = bool(tool_names) and tool_names <= self._investigation_tools
            if delivery_attempt or delivery_success:
                self._zero_write_investigation_rounds = 0
                self._zero_write_warned = False
            elif investigation_only:
                self._zero_write_investigation_rounds += 1
            elif tool_names:
                # Mixed / non-investigation activity — not pure read-idle.
                self._zero_write_investigation_rounds = 0
                self._zero_write_warned = False

    def note_empty_round(self, is_empty: bool) -> None:
        """Track consecutive empty-response rounds (B2).

        An empty round = the model produced no content and called no tool. A
        non-empty round (real answer OR a tool call) resets the streak — so only
        *consecutive* empties escalate toward a degraded finish.
        """
        self._consecutive_empty = self._consecutive_empty + 1 if is_empty else 0

    def empty_response_action(self) -> Intervention:
        """Decide what to do after an empty round (B2 degraded ladder).

        ``FINALIZE`` once the consecutive-empty streak hits the threshold (the turn
        ends as degraded rather than blank); else ``CONTINUE`` (retry the round on the
        same model).
        """
        if self._consecutive_empty >= self._empty_threshold:
            return Intervention.FINALIZE
        return Intervention.CONTINUE

    def tool_circuit_breaker(self) -> CircuitBreak:
        """Tools whose cumulative failures crossed a threshold (call after ``record``).

        Returns the tools that *newly* hit the warn / disable threshold this round
        (each transition fires once per tool per run). The engine injects the
        :meth:`CircuitBreak.message` and removes any ``disabled`` tools from the
        toolset for the remaining rounds. A tool that leaps straight to the disable
        count is only disabled (no redundant warn).
        """
        newly_warned: list[str] = []
        newly_disabled: list[str] = []
        for name, count in self._tool_failures.items():
            if name in self._tool_disabled:
                continue
            if count >= self._tool_failure_disable:
                self._tool_disabled.add(name)
                self._tool_warned.discard(name)
                newly_disabled.append(name)
            elif count >= self._tool_failure_warn and name not in self._tool_warned:
                self._tool_warned.add(name)
                newly_warned.append(name)
        tripped = (*newly_warned, *newly_disabled)
        parse_only = frozenset(
            name
            for name in tripped
            if self._tool_failures[name] > 0
            and self._tool_parse_failures.get(name, 0) == self._tool_failures[name]
        )
        retire_message = None
        if newly_disabled and self._pending_retire_message:
            retire_message = self._pending_retire_message
            self._pending_retire_message = None
        return CircuitBreak(
            warned=tuple(newly_warned),
            disabled=tuple(newly_disabled),
            parse_only=parse_only,
            retire_message=retire_message,
        )

    def tool_failure_count(self, tool_name: str) -> int:
        """Cumulative failure count for one tool in this run (circuit breaker input)."""
        return int(self._tool_failures.get(tool_name, 0))

    def tool_failure_facts(self) -> list[Any]:
        """Per-tool failure facts for tools that failed at least once this run.

        Returns :class:`~agentcore.runtime.tool_failures.ToolFailureFact` instances
        (typed as Any here to keep this module import-light at class body time).
        """
        from agentcore.runtime.tool_failures import ToolFailureFact

        facts: list[ToolFailureFact] = []
        for name, count in sorted(self._tool_failures.items()):
            if count <= 0:
                continue
            facts.append(
                ToolFailureFact(
                    tool_name=name,
                    failure_count=int(count),
                    last_error=self._tool_last_error.get(name, ""),
                    succeeded_after=bool(self._tool_succeeded_after_fail.get(name, False)),
                )
            )
        return facts

    def outstanding_tool_failures(self) -> list[Any]:
        """Failures not cancelled by a later success of the same tool."""
        return [f for f in self.tool_failure_facts() if f.outstanding]

    def note_round_productivity(
        self, *, had_tool_calls: bool, all_failed: bool, had_content: bool
    ) -> None:
        """Track consecutive *unproductive* rounds (B2 无产出早停).

        An unproductive round = the model called ≥1 tool, every call failed, and it
        produced no content. Any productive round — content this round, a tool
        success, or a no-tool round (handled by the empty/degraded path) — resets
        the streak, so only a sustained all-failing-no-output run escalates.
        """
        unproductive = had_tool_calls and all_failed and not had_content
        self._consecutive_unproductive = self._consecutive_unproductive + 1 if unproductive else 0

    def unproductive_early_stop(self) -> bool:
        """True once the consecutive-unproductive streak hits the threshold."""
        return self._consecutive_unproductive >= self._unproductive_threshold

    def has_recent_progress(self) -> bool:
        """True when this or the previous tool round succeeded a PROGRESS_TOOLS call."""
        return self._rounds_since_progress is not None and self._rounds_since_progress <= 1

    def reflection_due(self, round_idx: int) -> bool:
        """Whether to inject a periodic progress-review reflection (B2 反思注入).

        Fires on a fixed cadence — at ``reflection_start_round`` (0-indexed) and every
        ``reflection_interval`` rounds after (default: round_idx 3 / 6 / 9 …, i.e. the
        4th / 7th / 10th round). Skipped when this or the previous round already had a
        successful progress tool (落盘 / 交接 / 委派 / 提问), **or** when a reflection
        was already injected since the last progress (one soft review per idle streak;
        zero_write / convergence handle sustained thrashing). The prompt comes from
        :func:`progress_review_prompt`. Independent of the stuck detector.
        """
        if round_idx < self._reflection_start_round:
            return False
        if self.has_recent_progress():
            return False
        if self._reflection_latched_since_progress:
            return False
        return (round_idx - self._reflection_start_round) % self._reflection_interval == 0

    def mark_reflection_injected(self) -> None:
        """Latch soft 进度复盘 until the next successful PROGRESS_TOOLS call."""
        self._reflection_latched_since_progress = True

    @property
    def investigation_tool_names(self) -> frozenset[str]:
        """Read-only investigation tool names classified for this run."""
        return self._investigation_tools

    @property
    def investigation_calls(self) -> int:
        """Cumulative read-only investigation calls this run (finalize-log diagnostic)."""
        return self._investigation_calls

    @property
    def local_recon_calls(self) -> int:
        """Cumulative local peek calls (file_list / file_read / grep) this run."""
        return self._local_recon_calls

    @property
    def investigation_rounds(self) -> int:
        """Rounds with >=1 read-only investigation call (the safety net's batch-robust clock)."""
        return self._investigation_rounds

    @property
    def zero_write_finalize_rounds(self) -> int:
        """Configured delivery-idle thrashing threshold (0 = disabled)."""
        return self._zero_write_finalize_rounds

    @property
    def prose_idle(self) -> bool:
        """True when idle ladder is prose short-budget mode (handoff = delivery)."""
        return self._prose_idle

    @property
    def form_prose(self) -> bool:
        """True when deliverable.form=prose (reflection must not urge write tools)."""
        return self._form_prose

    @property
    def zero_write_investigation_rounds(self) -> int:
        """Consecutive investigation-only rounds with no delivery (landing / handoff)."""
        return self._zero_write_investigation_rounds

    @property
    def landing_succeeded(self) -> bool:
        """True once delivery succeeded (landing write, or handoff in prose_idle)."""
        return self._landing_succeeded

    def zero_write_warn_due(self) -> bool:
        """True once at threshold−1 (one-shot); caller injects hard warn then latches."""
        bar = self._zero_write_finalize_rounds
        if bar <= 1 or self._landing_succeeded or self._zero_write_warned:
            return False
        return self._zero_write_investigation_rounds >= bar - 1

    def mark_zero_write_warned(self) -> None:
        """Latch the one-shot zero-write warn so it cannot re-fire."""
        self._zero_write_warned = True

    def convergence_action(self) -> Intervention:
        """Over-investigation finalize: progress-aware spinning, zero-write, absolute cap.

        Spinning = consecutive investigation-only rounds re-reading the same targets
        (same tool+args fingerprints, or a subset of the prior round). Reading new
        files each round does not trip spinning. Zero-write (files-expected only)
        trips when investigation-only rounds accumulate with no landing success.
        The absolute ``finalize_rounds`` cap is a hard backstop for true runaways.
        Each path disabled when its threshold <= 0.
        """
        if (
            self._convergence_spin_rounds > 0
            and self._same_target_investigation_streak >= self._convergence_spin_rounds
        ):
            return Intervention.FINALIZE
        if (
            self._zero_write_finalize_rounds > 0
            and not self._landing_succeeded
            and self._zero_write_investigation_rounds >= self._zero_write_finalize_rounds
        ):
            return Intervention.FINALIZE
        if self._convergence_finalize_rounds <= 0:
            return Intervention.CONTINUE
        if self._investigation_rounds >= self._convergence_finalize_rounds:
            return Intervention.FINALIZE
        return Intervention.CONTINUE

    @property
    def same_target_investigation_streak(self) -> int:
        """Consecutive investigation-only rounds re-reading the same targets."""
        return self._same_target_investigation_streak

    def is_thrashing(self) -> bool:
        """Read-only run-health verdict for a HARD-CEILING termination boundary.

        When a hard ceiling (token backstop / max rounds) forces the run to stop —
        as opposed to the model choosing to finish — this routes the finalize: a
        *thrashing* run (sustained all-failing-no-output rounds, over-investigation
        spinning / absolute-cap, or files-expected zero-write idle) should finish
        DEGRADED and surface an observable signal, while an *on-track* run (made real
        progress, just ran out of budget) should finalize normally and deliver.

        Distinct from the per-round governance triggers (which stop the loop
        mid-run): those already fired earlier if they were going to, so at a natural
        max-rounds exit this is usually ``False`` (= deliver). It matters most for the
        token backstop, which can break the loop at any round. No side effects.
        """
        if self.unproductive_early_stop():
            return True
        return self.convergence_action() is Intervention.FINALIZE

    def detect(self) -> StuckSignal | None:
        """Return the strongest stuck signal in the window, or ``None``.

        Priority: repeated failure (most actionable) > repeated call > A-B-A-B.
        """
        if len(self._recent) < self._threshold:
            return None

        fail_counts = Counter(a.fingerprint for a in self._recent if not a.success)
        for attempt in reversed(self._recent):
            if not attempt.success and fail_counts[attempt.fingerprint] >= self._threshold:
                return StuckSignal(
                    StuckReason.REPEATED_FAILURE,
                    attempt.tool_name,
                    fail_counts[attempt.fingerprint],
                )

        all_counts = Counter(a.fingerprint for a in self._recent)
        for attempt in reversed(self._recent):
            if all_counts[attempt.fingerprint] >= self._threshold:
                return StuckSignal(
                    StuckReason.REPEATED_CALL,
                    attempt.tool_name,
                    all_counts[attempt.fingerprint],
                )

        if len(self._recent) >= 4:
            w, x, y, z = (
                self._recent[-4],
                self._recent[-3],
                self._recent[-2],
                self._recent[-1],
            )
            if (
                w.fingerprint == y.fingerprint
                and x.fingerprint == z.fingerprint
                and w.fingerprint != x.fingerprint
            ):
                return StuckSignal(StuckReason.ALTERNATING, z.tool_name, 2)

        return None

    def decide(self, signal: StuckSignal | None) -> Intervention:
        """Map a signal to an action via a two-strike ladder.

        First trip → ``NUDGE`` and clear the window, giving the model a clean
        slate to recover (so stale repeats don't immediately re-trigger). A
        subsequent trip → ``FINALIZE``.
        """
        if signal is None:
            return Intervention.CONTINUE
        if not self._nudged:
            self._nudged = True
            self._recent.clear()
            return Intervention.NUDGE
        return Intervention.FINALIZE
