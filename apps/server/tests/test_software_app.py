"""Software / app intent predicates + thin none-path helpers."""

from agentcore.runtime.runs.software_app import (
    is_software_app_intent,
    is_software_thin_html_none_path,
    software_none_path_blocked,
)


def test_is_software_app_intent_positives():
    assert is_software_app_intent("帮我做一个思维导图软件")
    assert is_software_app_intent("做一个笔记应用")
    assert is_software_app_intent("Build a todo app")
    assert is_software_app_intent("开发一个桌面应用")
    assert is_software_app_intent("手写构建软件旁路 build_feature 未在目录")


def test_is_software_app_intent_excludes_site_and_toolshed():
    assert not is_software_app_intent("帮我做个官网")
    assert not is_software_app_intent("帮我做一个运营控制台")
    assert not is_software_app_intent("搭建管理后台")
    assert not is_software_app_intent("写一份调研报告")
    assert not is_software_app_intent("把超时改成 30s")


def test_thin_html_none_path_detection():
    assert is_software_thin_html_none_path(
        {
            "playbook_none_reason": "单 HTML 即可",
            "tasks": [
                {"role": "前端工程师", "task": "写 mindmap.html"},
            ],
        }
    )
    assert is_software_thin_html_none_path(
        {
            "playbook_none_reason": "因为单文件就够",
            "tasks": [{"role": "前端", "task": "实现界面"}],
        }
    )
    # multi-role → not thin
    assert not is_software_thin_html_none_path(
        {
            "playbook_none_reason": "自定义多角色",
            "tasks": [
                {"role": "后端", "task": "API"},
                {"role": "前端", "task": "UI"},
            ],
        }
    )
    # user-confirmed delivery escape
    assert not is_software_thin_html_none_path(
        {
            "playbook_none_reason": "用户已确认交付形态为可运行单页原型",
            "tasks": [{"role": "前端工程师", "task": "mindmap.html"}],
        }
    )


def test_software_none_path_blocked_combines_intent():
    assert software_none_path_blocked(
        {
            "playbook_none_reason": "单 HTML 基础版",
            "tasks": [{"role": "前端工程师", "task": "app.html"}],
        },
        user_message="帮我做一个思维导图软件",
    )
    assert not software_none_path_blocked(
        {
            "playbook_none_reason": "单 HTML 基础版",
            "tasks": [{"role": "前端工程师", "task": "app.html"}],
        },
        user_message="帮我做个落地页网站",
    )
