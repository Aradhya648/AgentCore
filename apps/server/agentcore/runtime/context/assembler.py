"""ContextAssembler — the single seam that stitches system-prompt fragments.

上下文注入统一 Step 1（装配主干）+ Step 2（常驻源插件化）. Before Step 1 the system prompt
was built by ad-hoc string concatenation scattered across ``runtime.resolve.prompt``. Step 1
collected those fragments into one assembler; Step 2 made each fragment a uniform
:class:`PromptContributor` plugin carrying its own ``order`` (and a reserved ``budget``),
so:

- every injected fragment has a stable ``key`` (debuggable / addressable),
- ordering is DECLARATIVE (each contributor's :class:`SectionOrder`), not implicit in the
  ``.add()`` call sequence — the render order is the same no matter what sequence a site
  contributes in, and
- the future levers (priority / token budget — 文档「扳机 B」) get ONE place to plug into.

Behavior-preserving today: with the ``SectionOrder`` values the call sites pass, the
sorted render reproduces the prior inline order exactly, joined with ``"\\n"`` —
byte-identical to the old assembly. That byte-identity is load-bearing: the CEO/worker
system prefix must stay stable within a day or DeepSeek's exact-prefix cache is busted for
the whole hint stack that follows (see ``runtime.resolve.prompt`` and ``pipeline.run``).
"""

from __future__ import annotations

from agentcore.core.logging import get_logger
from agentcore.runtime.context.contributor import PromptContributor

logger = get_logger(__name__)


class ContextAssembler:
    """Collects :class:`PromptContributor` plugins and renders the system prompt.

    Usage mirrors the concatenation it replaces, now with an explicit order::

        text = (
            ContextAssembler()
            .add("base", base_prompt, SectionOrder.BASE)
            .add("memory_rules", rules_or_none, SectionOrder.MEMORY)  # None / "" skipped
            .render()
        )

    ``add`` / ``contribute`` return ``self`` for fluent chaining and **skip falsy text**
    (``None`` or ``""``), exactly reproducing the prior ``if part: parts.append(part)``
    guards so optional sections (memory, attachments, an empty skill directory) drop out
    without leaving a blank line. ``render`` sorts the kept contributors by ``order``
    (stable — ties keep contribution order) and joins them with ``"\\n"``.
    """

    def __init__(self) -> None:
        self._contributors: list[PromptContributor] = []

    def contribute(self, contributor: PromptContributor) -> ContextAssembler:
        """Add a plugin's contribution; no-op when its ``text`` is falsy (None / "")."""
        if contributor.text:
            self._contributors.append(contributor)
        return self

    def add(
        self, key: str, text: str | None, order: int, *, budget: int | None = None
    ) -> ContextAssembler:
        """Ergonomic sugar: build a :class:`PromptContributor` and contribute it.

        ``text`` is typed ``str | None`` so a site can pass an optional section straight
        through — a falsy one is skipped (no blank line), same guard as ``contribute``.
        """
        if text:
            self._contributors.append(
                PromptContributor(key=key, text=text, order=order, budget=budget)
            )
        return self

    def contributors(self) -> list[PromptContributor]:
        """The kept contributors in RENDER order (sorted; for debugging / budgeting)."""
        return sorted(self._contributors, key=lambda c: c.order)

    def observe(self, *, scope: str, soft_cap: int | None = None) -> ContextAssembler:
        """Log this prompt's assembled size + per-section chars — observe-only (COST-004).

        零行为副作用: 只埋点不改装配 (返回 ``self`` 供链式调用)。``cost.prompt_assembled`` 给出
        每段 chars 明细 (归因哪段膨胀) + 总 chars + 是否越软闸——为「开发期无真实数据」攒据, 待数据
        出再据此开「仅裁易变尾 (order≥800)」软闸 (项目审计-成本性能专项 §九)。trace / conversation
        上下文由 contextvars 自动并入每行日志, 故此处无需显式传。``soft_cap`` 为 None ⇒ 不判越限。
        """
        kept = sorted(self._contributors, key=lambda c: c.order)
        sections = {c.key: len(c.text) for c in kept}
        total = sum(sections.values())
        logger.info(
            "cost.prompt_assembled",
            scope=scope,
            total_chars=total,
            sections=sections,
            over_soft_cap=soft_cap is not None and soft_cap > 0 and total > soft_cap,
            soft_cap=soft_cap,
        )
        return self

    def render(self) -> str:
        """Sort kept contributors by ``order`` (stable) and join with ``"\\n"``."""
        return "\n".join(c.text for c in sorted(self._contributors, key=lambda c: c.order))
