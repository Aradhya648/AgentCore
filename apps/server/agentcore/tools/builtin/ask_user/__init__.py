"""ask_user — the CEO pauses the turn to ask the user (the one asking primitive).

CEO-only: wired in ``runtime.pipeline`` next to ``delegate`` and deliberately NOT in
``build_builtin_registry`` (a delegated worker never talks to the user). This is the
single「向用户发问」primitive — it absorbed the former 引导式开场 (``kickoff``): whether
the CEO is **opening** a producible-but-underspecified request (做网站 / 文档…) or
hitting a **mid-execution** high-cost fork (A vs B / an irreversible step), it asks the
SAME way and through the SAME mechanism.

Two modes, one primitive — the model picks via ``blocking``. DEFAULT (``blocking`` true):
suspend + resume — the card surfaces, the turn finalizes onto a durable frame
(``ToolEffect.SUSPEND``), and the user's answer returns via the cold ``POST .../resume``
path into the CEO's ReAct loop as this tool's result. 挂起+恢复 is the general case
(it preserves any in-flight context — delegate results, read files) and subsumes the
opening 引导 at negligible cost, so the runtime — not the model — owns「该结束还是该挂起」.
NON-BLOCKING (``blocking`` false, Cursor 式): for a low-stakes
fork the CEO already has a sensible default for, it surfaces the question, returns a
``CONTINUE`` immediately (no suspend, no durable frame, no extra round) and keeps working
on its stated default; the user's answer, if any, rides an ordinary next-turn message.
Requires a stated fallback (an ``assumptions`` entry or a question ``default``) — without
one「非阻塞」would silently guess, so it degrades to an error steering the CEO to block.
The model decides WHETHER to ask (restraint) and, when it does, whether the fork is worth
freezing the turn (block) or can ride a default (non-block). 对比与决策见
docs/03-AI核心/Agent协作模式.md（向用户发问 / 阻塞与非阻塞）.

The card's content is one adaptive shape (rich when opening, compact mid-task):
``message`` (the framing / opening line — always shown), optional ``context``
background, optional ``assumptions`` (起步计划 — low-impact decisions the CEO made for
the user, read-only chips), optional ``questions`` (the askable items, each pre-fillable
with a ``default`` so a 想省事 user one-clicks through), and optional ``style_options``
(visual products only). A mid-task A/B is just ``message`` + a one-item ``questions``.

A submit answer is ``ToolEffect.CONTINUE`` (the CEO resumes with the user's picks); a
stop is ``ToolEffect.INTERACT`` — a terminal effect that ends the turn gracefully in-band
(its closing note rides as ``ToolResult.final_text``). The question + answer are
journaled (``events._JOURNAL_EVENT_TYPES``) so a reload replays the exchange inline.

结构化挂起 2b + 挂起即收口 (②) / D11 (turn 级落盘 + ``POST .../resume``): like the
``delegate`` checkpoint hook, the suspend is backed by a durable frame — an
:class:`AskUserSuspension` is saved to ``paused_turns`` and the turn ends in place
(``SUSPEND→PAUSED``). All resumes — same session or after restart — go through the
single cold path ``POST .../resume``, which maps the user's answer back to this tool's
result and continues the CEO loop. If the frame cannot be saved ⇒ **explicit failure**
(no in-memory timed wait / no timeout auto-continue). The answer→result mapping is
:func:`result.ask_user_tool_result` so resume shares one source of truth.
"""

from agentcore.tools.builtin.ask_user.result import ask_user_tool_result
from agentcore.tools.builtin.ask_user.tool import AskUserTool

__all__ = ["AskUserTool", "ask_user_tool_result"]
