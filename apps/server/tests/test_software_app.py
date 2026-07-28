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


def test_is_software_greenfield_intent():
    from agentcore.runtime.runs.software_app import is_software_greenfield_intent

    assert is_software_greenfield_intent("从0到1搭建一个 Vue3 数据看板")
    assert is_software_greenfield_intent("帮我做一个完整的 Vite SPA 项目")
    assert is_software_greenfield_intent("按文档实现全部功能，开发 React 应用")
    assert not is_software_greenfield_intent("帮我做个官网")
    assert not is_software_greenfield_intent("帮我做一个运营控制台")
    assert not is_software_greenfield_intent("帮我调研竞品")
    # 裸「完整项目」/ 字面 build_app / 栈名 alone ≠ 绿场
    assert not is_software_greenfield_intent("审视完整项目结构与 monorepo")
    assert not is_software_greenfield_intent("对照 build_app playbook 写任务书")
    assert not is_software_greenfield_intent("技术栈含 React Vite monorepo")
    # 审计 / 只读框定即使夹带 React 也不是绿场
    assert not is_software_greenfield_intent(
        "做架构审计，覆盖 React / Vite / monorepo，不修改代码"
    )


def test_is_software_audit_readonly_exempt():
    from agentcore.runtime.runs.software_app import is_software_audit_readonly_exempt

    assert is_software_audit_readonly_exempt("对项目做全面审计、不修改代码")
    assert is_software_audit_readonly_exempt("质量敏感成品独立审计，1名审计员")
    assert is_software_audit_readonly_exempt("read-only code review, no code changes")
    assert not is_software_audit_readonly_exempt("从0到1搭建一个 Vue3 数据看板")


def test_software_greenfield_none_path_audit_exempt():
    """误伤形态（trace c1a34615…）：用户要全面审计不改码 + 任务书含 React/monorepo/审计员 → 放行."""
    from agentcore.runtime.runs.software_app import software_greenfield_none_path_blocked

    assert not software_greenfield_none_path_blocked(
        {
            "playbook_none_reason": "多角度并行只读审计",
            "tasks": [
                {
                    "role": "审计员",
                    "task": (
                        "对 AgentCore monorepo 做架构审计；"
                        "技术栈含 React / Electron / Vite；只读、不修改代码"
                    ),
                },
                {
                    "role": "审计员",
                    "task": "代码健康审计，对照 build_app 文档仅作参考",
                },
            ],
        },
        user_message="对项目做全面审计、不修改代码",
    )


def test_software_greenfield_none_path_true_spa_still_blocked():
    from agentcore.runtime.runs.software_app import software_greenfield_none_path_blocked

    assert software_greenfield_none_path_blocked(
        {
            "playbook_none_reason": "手写前后端",
            "tasks": [
                {"role": "前端", "task": "搭 Vite 脚手架"},
                {"role": "前端", "task": "写看板页面"},
            ],
        },
        user_message="从0到1做一个 Vue SPA",
    )

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
