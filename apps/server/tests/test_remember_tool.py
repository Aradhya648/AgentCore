"""CEO remember tool — records an explicit user directive as a USER RULE (§5.7 分流).

DB-free here: the schema contract + the pure dedup helper. The end-to-end write (directive →
``role='rule', ai_maintained=false`` document, immediate injection) is exercised against a real
schema in ``tests/integration/test_documents.py``.
"""

from agentcore.memory.rules_injection import append_user_rule_bullet
from agentcore.tools.builtin.remember import RememberTool, build_remember_tool


def test_remember_schema_is_static():
    tool = RememberTool(folder_id=None)
    assert tool.schema.name == "remember"
    # Steers the model to the split: explicit directive here, inferred preferences to巩固.
    assert "明确" in tool.schema.description
    assert set(tool.schema.parameters["required"]) == {"content"}
    assert tool.schema.parameters["properties"]["scope"]["enum"] == ["global", "project"]


def test_build_remember_tool_defaults():
    tool = build_remember_tool(folder_id="fold-1")
    assert isinstance(tool, RememberTool)
    assert tool.folder_id == "fold-1"


def test_append_user_rule_bullet_adds_and_dedupes():
    md, changed = append_user_rule_bullet("", "以后都用中文回复")
    assert changed is True
    assert md == "- 以后都用中文回复\n"

    # A normalized duplicate (whitespace-only difference) is a no-op — re-remembering never grows.
    md2, changed2 = append_user_rule_bullet(md, "以后都用中文回复  ")
    assert changed2 is False
    assert md2 == md

    # A genuinely new rule appends as another bullet.
    md3, changed3 = append_user_rule_bullet(md, "别用表格")
    assert changed3 is True
    assert md3 == "- 以后都用中文回复\n- 别用表格\n"


def test_append_user_rule_bullet_ignores_blank():
    assert append_user_rule_bullet("- x\n", "   ") == ("- x\n", False)
