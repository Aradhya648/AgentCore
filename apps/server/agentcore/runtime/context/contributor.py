"""PromptContributor — the uniform "plugin" shape every always-on prompt source takes.

上下文注入统一 Step 2（常驻源插件化）. Step 1 centralized the *assembly* (ContextAssembler);
this gives every always-on source — base prompt, runtime context, memory ``<rules>``, CEO
core, skill directory, citation hint, workspace overview, per-turn attachment — ONE shape:
a named fragment + its render ``order`` + an optional ``budget``. So:

- ordering is DECLARATIVE in one place (:class:`SectionOrder`), not implicit in the
  ``.add()`` call sequence at each site, and
- the future budget / eviction lever (文档「扳机 B」) reads ``budget`` off the contributor
  instead of needing N scattered call sites to grow a budget argument.

Eager by design: the owner computes ``text`` (some sources are async, e.g. the workspace
overview) and hands the finished string here — this is a descriptor, not a lazy renderer.
A falsy ``text`` (None / "") means "this source contributes nothing this turn" and is
dropped, exactly as the prior ``if part: parts.append(part)`` guards did.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class SectionOrder(IntEnum):
    """Canonical render order of system-prompt sections, foundation → volatile tail.

    One ordering universe so every assembler renders sections in the same relative order
    regardless of the sequence that contributed them. Spaced by 100 to leave room for
    future sections to slot between without renumbering. The tail (workspace overview,
    attachment) is deliberately LAST so the stable foundation/hint prefix stays
    byte-identical within a day — load-bearing for DeepSeek's exact-prefix cache.
    """

    BASE = 100
    RUNTIME_CONTEXT = 200
    # Per-turn environment facts (location / desktop / capabilities). Volatile with
    # binding changes; sits after the date line so the shared base can carry it to
    # both CEO and workers without riding the CEO-only overview tail.
    WORKSPACE_FACTS = 250
    MEMORY = 300
    CEO_CORE = 400
    SKILL_DIRECTORY = 500
    # The 记忆主题目录 (consult_memory's catalog) sits beside the skill directory:
    # both are "here is a catalog, pull the full text by name" blocks (记忆文件夹化 §六).
    # CEO gets name+summary; workers get a simplified names-only variant.
    MEMORY_TOPICS = 550
    CITATION = 600
    CEO_VISUALIZATION = 700
    WORKSPACE_OVERVIEW = 800
    # CEO-only conversation state: the newest appendable team graph (跨回合同图追加's
    # cross-turn id echo — history replays no tool I/O, so it rides the volatile tail).
    RECENT_TEAM_GRAPH = 850
    ATTACHMENT = 900


@dataclass(frozen=True)
class PromptContributor:
    """One always-on source's contribution to the system prompt.

    ``key`` is a stable identifier (debuggable / addressable; not rendered). ``text`` is
    the verbatim fragment — the owner keeps owning exact wording + whitespace. ``order``
    places it (see :class:`SectionOrder`). ``budget`` is the max chars a future budgeted
    assembler may trim it to — ``None`` = unbounded; today nothing enforces it, the field
    exists so 扳机 B has one place to read.
    """

    key: str
    text: str
    order: int
    budget: int | None = None
