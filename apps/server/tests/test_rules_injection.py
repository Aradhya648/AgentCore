"""Two-tier rule injection + cross-file budget (Agent记忆与知识系统 §二 / §5.7).

Pure, DB-free: the budget/compose logic (``compose_injected_rules``) and the ``<rules>`` two-tier
wording (``assemble_system_prompt``). The DB loader (``assemble_injected_rules``) is covered in
``tests/integration/test_documents.py``.
"""

from agentcore.memory.rules_injection import RuleFragment, compose_injected_rules
from agentcore.runtime.resolve.prompt import assemble_system_prompt

_BIG = {"max_docs": 100, "max_chars": 100_000}


def test_compose_memory_only_matches_legacy_concatenation():
    # No user rules + under budget → user body empty, memory body = the legacy join order
    # (偏好, 画像, then the project-labeled layer). Byte-stability with load_injected_memory.
    frags = [
        RuleFragment("global", "ai", "偏好体"),
        RuleFragment("global", "ai", "画像体"),
        RuleFragment("project", "ai", "（项目标签）\n项目体"),
    ]
    user_md, memory_md = compose_injected_rules(frags, **_BIG)
    assert user_md == ""
    assert memory_md == "偏好体\n\n画像体\n\n（项目标签）\n项目体"


def test_compose_user_rules_first_then_memory():
    frags = [
        RuleFragment("global", "user", "规则A"),
        RuleFragment("project", "user", "（项目规则）\n规则B"),
        RuleFragment("global", "ai", "画像体"),
    ]
    user_md, memory_md = compose_injected_rules(frags, **_BIG)
    assert user_md == "规则A\n\n（项目规则）\n规则B"
    assert memory_md == "画像体"


def test_compose_empty_when_no_fragments():
    assert compose_injected_rules([], **_BIG) == ("", "")


def test_budget_global_survives_over_project():
    # 全局优先存活 (§5.3): with room for one doc, the GLOBAL layer survives, the project drops.
    frags = [
        RuleFragment("global", "ai", "G" * 100),
        RuleFragment("project", "ai", "（项目）\n" + "P" * 100),
    ]
    user_md, memory_md = compose_injected_rules(frags, max_docs=1, max_chars=100_000)
    assert memory_md == "G" * 100
    assert "P" * 100 not in memory_md


def test_budget_user_rule_survives_over_ai_in_same_scope():
    # Within a scope, the user's authoritative rule outlives soft AI memory when budget is tight.
    frags = [
        RuleFragment("global", "ai", "画像体"),
        RuleFragment("global", "user", "必须用中文"),
    ]
    user_md, memory_md = compose_injected_rules(frags, max_docs=1, max_chars=100_000)
    assert user_md == "必须用中文"
    assert memory_md == ""


def test_budget_char_cap_drops_overflow_keeping_global():
    frags = [
        RuleFragment("global", "ai", "A" * 50),
        RuleFragment("project", "ai", "（项目）\n" + "B" * 50),
    ]
    # Only the first fits under 60 chars; the project layer overflows and is dropped.
    user_md, memory_md = compose_injected_rules(frags, max_docs=100, max_chars=60)
    assert memory_md == "A" * 50


def test_nonpositive_budget_admits_all():
    frags = [RuleFragment("global", "user", "r1"), RuleFragment("project", "ai", "m1")]
    user_md, memory_md = compose_injected_rules(frags, max_docs=0, max_chars=0)
    assert user_md == "r1" and memory_md == "m1"


def test_assemble_system_prompt_two_tier_wording():
    out = assemble_system_prompt(
        memory_markdown="- 倾向简洁回复",
        user_rules_markdown="- 必须始终用中文",
    )
    assert "<rules>" in out and "</rules>" in out
    # Both tiers present; user rules ahead of memory.
    assert "必须始终用中文" in out and "倾向简洁回复" in out
    assert out.index("必须始终用中文") < out.index("倾向简洁回复")
    # Authority carried by wording: user rules framed as 须遵守, memory as 软性偏好.
    assert "用户规则" in out and "须" in out
    assert "软性偏好" in out
    # The routing fence still guards memory in the combined block.
    assert "不得改变本回合路由" in out


def test_assemble_system_prompt_memory_only_uses_legacy_block():
    # With no user rules the block stays the memory-only template (byte-stability / prefix cache):
    # no user-rule framing, the legacy memory framing intact.
    out = assemble_system_prompt(memory_markdown="- 倾向简洁回复")
    assert "用户规则 · 须严格遵守" not in out
    assert "长期记忆" in out and "软性偏好" in out
    assert "倾向简洁回复" in out
