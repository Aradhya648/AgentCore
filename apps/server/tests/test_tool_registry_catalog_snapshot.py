"""Snapshot lock: builtin / worker / CEO registries + capability catalog.

Written BEFORE the declarative registration convergence so a refactor that
changes roster, order, audience, or approval fails loudly. New tools update
this snapshot alongside their declaration.
"""

from __future__ import annotations

from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.tools.builtin import (
    approval_class_tool_names,
    build_builtin_registry,
    build_ceo_tool_registry,
    build_worker_registry,
    delegation_grantable_tool_names,
    file_mutation_tool_names,
    per_call_tool_names,
)
from agentcore.tools.catalog import (
    AVAILABLE_TO_CEO,
    AVAILABLE_TO_WORKER,
    build_capability_catalog,
)

# Ordered names — registration order is part of the public surface (catalog /
# OpenAI defs). Keep in lockstep with tools.registration.DECLARED_TOOLS.
_BUILTIN_ORDER = [
    "web_search",
    "read_url",
    "file_read",
    "file_write",
    "file_append",
    "str_replace",
    "write_section",
    "file_list",
    "file_delete",
    "file_move",
    "file_copy",
    "mkdir",
    "file_batch",
    "grep",
    "code_search",
    "git",
    "test_run",
    "code_execute",
]

_WORKER_ONLY_ORDER = [
    "escalate",
    "post_note",
    "read_notes",
    "amend_note",
    "handoff",
    "desktop_notify",
]

_CEO_BUILTIN_ORDER = [
    "web_search",
    "read_url",
    "file_read",
    "file_list",
    "grep",
    "code_search",
    "git",
]

_CATALOG_ORCHESTRATION_ORDER = [
    "delegate",
    "replan",
    "debate",
    "consult_skill",
    "consult_memory",
    "remember",
    "update_project_profile",
    "ask_user",
    "board_ops",
    "board_read",
]

_CATALOG_AVAILABLE_TO: dict[str, tuple[str, ...]] = {
    # Shared read/retrieval built-ins
    "web_search": (AVAILABLE_TO_CEO, AVAILABLE_TO_WORKER),
    "read_url": (AVAILABLE_TO_CEO, AVAILABLE_TO_WORKER),
    "file_read": (AVAILABLE_TO_CEO, AVAILABLE_TO_WORKER),
    "file_list": (AVAILABLE_TO_CEO, AVAILABLE_TO_WORKER),
    "grep": (AVAILABLE_TO_CEO, AVAILABLE_TO_WORKER),
    "code_search": (AVAILABLE_TO_CEO, AVAILABLE_TO_WORKER),
    "git": (AVAILABLE_TO_CEO, AVAILABLE_TO_WORKER),
    # Worker-only mutation / execution / collaboration
    "file_write": (AVAILABLE_TO_WORKER,),
    "file_append": (AVAILABLE_TO_WORKER,),
    "str_replace": (AVAILABLE_TO_WORKER,),
    "write_section": (AVAILABLE_TO_WORKER,),
    "file_delete": (AVAILABLE_TO_WORKER,),
    "file_move": (AVAILABLE_TO_WORKER,),
    "file_copy": (AVAILABLE_TO_WORKER,),
    "mkdir": (AVAILABLE_TO_WORKER,),
    "file_batch": (AVAILABLE_TO_WORKER,),
    "test_run": (AVAILABLE_TO_WORKER,),
    "code_execute": (AVAILABLE_TO_WORKER,),
    "escalate": (AVAILABLE_TO_WORKER,),
    "post_note": (AVAILABLE_TO_WORKER,),
    "read_notes": (AVAILABLE_TO_WORKER,),
    "amend_note": (AVAILABLE_TO_WORKER,),
    "handoff": (AVAILABLE_TO_WORKER,),
    "desktop_notify": (AVAILABLE_TO_WORKER,),
    # CEO orchestration (catalog advertise)
    "delegate": (AVAILABLE_TO_CEO,),
    "replan": (AVAILABLE_TO_CEO,),
    "debate": (AVAILABLE_TO_CEO,),
    "consult_skill": (AVAILABLE_TO_CEO,),
    "consult_memory": (AVAILABLE_TO_CEO, AVAILABLE_TO_WORKER),
    "remember": (AVAILABLE_TO_CEO,),
    "update_project_profile": (AVAILABLE_TO_CEO,),
    "ask_user": (AVAILABLE_TO_CEO,),
    "board_ops": (AVAILABLE_TO_CEO,),
    "board_read": (AVAILABLE_TO_CEO,),
}


def test_tool_registry_builtin_order_and_roster():
    names = [s.name for s in build_builtin_registry().list_all()]
    assert names == _BUILTIN_ORDER


def test_tool_registry_worker_default_order_and_roster():
    names = [s.name for s in build_worker_registry().list_all()]
    assert names == _BUILTIN_ORDER + _WORKER_ONLY_ORDER


def test_tool_registry_ceo_builtin_order_and_roster():
    names = [s.name for s in build_ceo_tool_registry().list_all()]
    assert names == _CEO_BUILTIN_ORDER


def test_tool_registry_builtin_approvals_snapshot():
    approvals = {s.name: s.approval for s in build_builtin_registry().list_all()}
    never = {
        "web_search",
        "read_url",
        "file_read",
        "file_list",
        "grep",
        "code_search",
        "git",
    }
    grantable = set(_BUILTIN_ORDER) - never
    for name in never:
        assert approvals[name] is ToolApproval.NEVER
    for name in grantable:
        assert approvals[name] is ToolApproval.GRANTABLE


def test_tool_registry_grant_sets_snapshot():
    assert file_mutation_tool_names() == frozenset(
        {
            "file_write",
            "file_append",
            "str_replace",
            "write_section",
            "file_delete",
            "file_move",
            "file_copy",
            "mkdir",
            "file_batch",
        }
    )
    assert approval_class_tool_names() == file_mutation_tool_names() | frozenset({"git"})
    assert delegation_grantable_tool_names() == approval_class_tool_names() | frozenset(
        {
            "code_execute",
            "test_run",
            "terminal",
            # L3 团队浏览器 (D11): execution_class → covered by a delegation grant.
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_snapshot",
            "browser_screenshot",
        }
    )
    assert per_call_tool_names() == frozenset()


def test_catalog_order_and_available_to_snapshot():
    catalog = build_capability_catalog()
    names = [e.schema.name for e in catalog]
    assert names == _BUILTIN_ORDER + _WORKER_ONLY_ORDER + _CATALOG_ORCHESTRATION_ORDER
    by_name = {e.schema.name: e for e in catalog}
    assert set(by_name) == set(_CATALOG_AVAILABLE_TO)
    for name, expected in _CATALOG_AVAILABLE_TO.items():
        assert by_name[name].available_to == expected, name


def test_catalog_categories_present():
    """Every catalog entry keeps a real ToolCategory (governance UI)."""
    for entry in build_capability_catalog():
        assert isinstance(entry.schema.category, ToolCategory)
        assert isinstance(entry.schema.approval, ToolApproval)


def test_tool_registry_declarations_cover_roster():
    """Every declared class has ``registration``; CEO builtins stay NEVER-aligned."""
    from agentcore.tools.registration import (
        AUDIENCE_CEO,
        CeoWire,
        ToolSurface,
        declared_tool_name,
        declared_tools,
        tool_registration,
    )

    declared = declared_tools()
    assert declared, "DECLARED_TOOLS must not be empty"
    names = [declared_tool_name(cls) for cls in declared]
    assert len(names) == len(set(names)), f"duplicate declared names: {names}"

    for cls in declared_tools(surface=ToolSurface.BUILTIN):
        reg = tool_registration(cls)
        if AUDIENCE_CEO in reg.audience:
            # Coordinator may only hold auto-run tools.
            schema = cls().schema if not reg.needs_location else cls(location=None).schema
            assert schema.approval is ToolApproval.NEVER, schema.name

    # CEO orchestration wire gates (construction stays in prepare / ceo_surface / board).
    wire_by_name = {
        declared_tool_name(cls): tool_registration(cls).ceo_wire
        for cls in declared_tools(surface=ToolSurface.CEO_ORCHESTRATION)
    }
    assert wire_by_name == {
        "delegate": CeoWire.ALWAYS,
        "replan": CeoWire.COORDINATION,
        "debate": CeoWire.ALWAYS,
        "consult_skill": CeoWire.ALWAYS,
        "consult_memory": CeoWire.MEMORY,
        "remember": CeoWire.MEMORY,
        "update_project_profile": CeoWire.MEMORY,
        "ask_user": CeoWire.CHECKPOINT,
        "board_ops": CeoWire.BOARD,
        "board_read": CeoWire.BOARD,
    }
