"""Unit tests for the context assembly spine (ContextAssembler + PromptContributor)."""

from __future__ import annotations

from agentcore.runtime.context import (
    ContextAssembler,
    PromptContributor,
    SectionOrder,
)


def test_render_sorts_by_order_not_contribution_sequence():
    # Contribute OUT of order; render must still follow `order` (the centralization win).
    out = (
        ContextAssembler()
        .add("attach", "ATT", SectionOrder.ATTACHMENT)
        .add("base", "BASE", SectionOrder.BASE)
        .add("memory", "MEM", SectionOrder.MEMORY)
        .render()
    )
    assert out == "BASE\nMEM\nATT"


def test_falsy_text_is_skipped_no_blank_line():
    out = (
        ContextAssembler()
        .add("base", "BASE", SectionOrder.BASE)
        .add("memory", None, SectionOrder.MEMORY)  # absent this turn
        .add("attach", "", SectionOrder.ATTACHMENT)  # empty
        .render()
    )
    assert out == "BASE"


def test_contribute_accepts_a_contributor_object():
    out = (
        ContextAssembler()
        .contribute(PromptContributor("a", "A", order=200))
        .contribute(PromptContributor("b", "B", order=100))
        .render()
    )
    assert out == "B\nA"


def test_equal_order_keeps_contribution_order_stable():
    out = ContextAssembler().add("first", "1", 500).add("second", "2", 500).render()
    assert out == "1\n2"


def test_contributors_returns_kept_in_render_order():
    asm = (
        ContextAssembler()
        .add("attach", "ATT", SectionOrder.ATTACHMENT)
        .add("base", "BASE", SectionOrder.BASE)
        .add("skip", None, SectionOrder.MEMORY)
    )
    keys = [c.key for c in asm.contributors()]
    assert keys == ["base", "attach"]  # sorted by order, falsy dropped


def test_budget_is_carried_but_not_enforced_today():
    # 扳机 B 预留：budget rides on the contributor; nothing trims yet.
    asm = ContextAssembler().add("base", "x" * 100, SectionOrder.BASE, budget=10)
    assert asm.render() == "x" * 100
    assert asm.contributors()[0].budget == 10


def test_observe_is_chainable_and_side_effect_free():
    # COST-004 仅观测起步: observe() only logs per-section chars — it returns self (chainable)
    # and the rendered prompt is byte-identical with or without it (zero behavior change).
    asm = (
        ContextAssembler()
        .add("base", "BASE", SectionOrder.BASE)
        .add("attach", "ATTACH", SectionOrder.ATTACHMENT)
    )
    before = asm.render()
    assert asm.observe(scope="test", soft_cap=1000) is asm  # chainable (returns self)
    assert asm.render() == before == "BASE\nATTACH"  # observe trimmed/changed nothing
