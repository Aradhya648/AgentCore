"""Playbook declaration gate: free teaming OK without playbook; site build hard-rejects bypass.

Website / toolshed build intent hard-rejects ``none`` / hand-written bypass (P1).
Software / app intent keeps narrow thin-HTML hard reject (no「优先 build_feature」).
Other non-site hand-written tasks pass without playbook or none reason.
"""

from agentcore.runtime.delegate.playbook_declaration import (
    declaration_reject_gate,
    is_website_none_rejected,
    resolve_playbook_declaration,
    website_none_path_blocked,
    website_none_rejected_message,
)
from agentcore.runtime.runs.software_app import (
    software_none_path_blocked,
    software_thin_html_rejected_message,
)
from tests.delegate.conftest import Provider, ctx, tool


def test_declaration_reject_gate_helpers():
    web = website_none_rejected_message()
    soft = software_thin_html_rejected_message()
    assert is_website_none_rejected(web)
    assert declaration_reject_gate(web) == "website"
    assert declaration_reject_gate(soft) == "software"
    assert declaration_reject_gate("delegate 须传手写 `tasks`，其余…") == "empty"
    assert declaration_reject_gate("未知 playbook『x』") == "unknown"
    assert not is_website_none_rejected(soft)
    # Probe must not rely on bare substring without backticks (old broken check).
    assert '禁止 playbook_id="none"' not in web  # message uses backticks
    assert is_website_none_rejected(web)  # prefix / constant compare is reliable


def test_resolve_handwritten_without_playbook_ok():
    """自由组队：不传 playbook，直接手写 tasks → 过。"""
    name, reason, err = resolve_playbook_declaration(
        {"tasks": [{"role": "a", "task": "调研并写报告"}]}
    )
    assert err is None
    assert name is None
    assert reason is None


def test_resolve_none_without_reason_ok():
    """显式 none 也不再强制理由（自由组队）。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "tasks": [{"role": "a", "task": "b"}],
        }
    )
    assert err is None
    assert name is None
    assert reason is None


def test_resolve_none_with_reason_ok():
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "playbook_none_reason": "机械单步改一句文案",
            "tasks": [{"role": "a", "task": "b"}],
        }
    )
    assert err is None
    assert name is None
    assert "机械单步" in (reason or "")


def test_resolve_named_playbook_ok():
    name, reason, err = resolve_playbook_declaration(
        {"playbook": "build_website", "playbook_args": {"site": "X"}}
    )
    assert err is None
    assert name == "build_website"
    assert reason is None


def test_resolve_empty_delegate_rejected():
    """无 tasks 且无具名 playbook → 拒。"""
    name, reason, err = resolve_playbook_declaration({})
    assert name is None and reason is None
    assert err is not None
    assert "tasks" in err
    assert "build_website" in err


def test_website_intent_none_rejected():
    """建站意图 + none → 拒（回归：consult miss 后手糊两节点旁路）。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "playbook_none_reason": "build_website 未在目录确认，手写内容+前端两阶段构建官网",
            "tasks": [
                {"role": "内容策略师", "task": "撰写官网文案"},
                {"role": "前端工程师", "task": "构建完整官网页面"},
            ],
        },
        user_message="帮我做个 GEO 营销官网",
    )
    assert name is None and reason is None
    assert err is not None
    assert "禁止" in err and "none" in err
    assert "build_website" in err


def test_website_intent_handwritten_without_declaration_rejected():
    """建站意图 + 缺省手写 tasks（不传 playbook）→ 仍硬拒。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "tasks": [
                {"role": "文案", "task": "写落地页文案"},
                {"role": "前端", "task": "实现落地页 HTML"},
            ],
        },
        user_message="帮我做一个落地页网站",
    )
    assert name is None and reason is None
    assert err is not None
    assert "build_website" in err


def test_website_intent_none_rejected_from_user_message_alone():
    """User turn clearly asks to build a site → vague none still blocked."""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "playbook_none_reason": "自定义拆法",
            "tasks": [{"role": "工程师", "task": "按要求交付"}],
        },
        user_message="帮我做一个落地页网站",
    )
    assert err is not None
    assert "build_website" in err


def test_website_intent_named_build_website_ok():
    """建站意图 + build_website → 过（声明闸只认名字；风格闸在 execute 另测）。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook": "build_website",
            "playbook_args": {"site": "面向中小商家的 GEO 营销官网"},
        },
        user_message="帮我做个官网",
    )
    assert err is None
    assert name == "build_website"
    assert reason is None


def test_toolshed_intent_none_rejected():
    """控制台意图 + none → 拒（修订 6：toolshed 纳入 none 硬闸）。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "playbook_none_reason": "手写内容+前端两阶段构建控制台",
            "tasks": [
                {"role": "内容", "task": "撰写控制台文案"},
                {"role": "前端", "task": "实现管理后台页面"},
            ],
        },
        user_message="帮我做一个运营控制台",
    )
    assert name is None and reason is None
    assert err is not None
    assert "禁止" in err and "none" in err
    assert "build_toolshed" in err


def test_toolshed_intent_named_build_toolshed_ok():
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook": "build_toolshed",
            "playbook_args": {"site": "订单运营控制台"},
        },
        user_message="帮我搭一个工具台",
    )
    assert err is None
    assert name == "build_toolshed"
    assert reason is None


def test_non_website_none_still_ok():
    """明显非建站 + none → 仍可（不误伤）。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "playbook_none_reason": "机械单步改一句配置",
            "tasks": [{"role": "工程师", "task": "把超时改成 30s"}],
        },
        user_message="把配置里的超时改一下",
    )
    assert err is None
    assert name is None
    assert reason is not None


def test_research_handwritten_no_prefer_pressure():
    """调研意图手写 tasks：可过；拒文/路径不再强推 research_report。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "tasks": [
                {"role": "调研员", "task": "写实务研究报告"},
                {"role": "写作者", "task": "成篇", "depends_on": ["调研员"]},
            ],
        },
        user_message="写一篇起诉第三者立案实务研究报告",
    )
    assert err is None
    assert name is None
    # optional named shape still expands
    name2, _, err2 = resolve_playbook_declaration(
        {
            "playbook": "research_report",
            "playbook_args": {"topic": "起诉第三者立案"},
        },
        user_message="写一篇调研报告",
    )
    assert err2 is None
    assert name2 == "research_report"


def test_website_followup_audit_none_exempt():
    """User 做过站，本拍是审计/修复 → none 豁免（call 无绿场构建意图）。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "playbook_none_reason": "质量敏感成品独立审计，1 名审计员覆盖前端+文案",
            "tasks": [
                {
                    "role": "审计员",
                    "task": "对 GEO 官网的两个交付物进行独立审计并出报告",
                }
            ],
        },
        user_message="帮我做个 GEO 官网",
    )
    assert err is None
    assert name is None
    assert "审计" in (reason or "")


def test_build_website_verify_named_ok_not_none_gate():
    """Second-act verify playbook is a named shape — declaration resolves, no none reject."""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook": "build_website_verify",
            "playbook_args": {"site": "GEO 官网"},
        },
        user_message="请对本站做第二段整页验收",
    )
    assert err is None
    assert name == "build_website_verify"
    assert reason is None


def test_website_verify_framing_followup_exempt():
    from agentcore.runtime.runs.website_style import is_website_followup_exempt

    assert is_website_followup_exempt("playbook=build_website_verify 整页验收")
    assert is_website_followup_exempt("页面 QA 续派")


def test_website_none_path_blocked_helper():
    assert website_none_path_blocked(
        {
            "playbook_none_reason": "手写构建官网",
            "tasks": [{"role": "前端", "task": "搭建网站"}],
        },
        user_message="",
    )
    assert not website_none_path_blocked(
        {
            "playbook_none_reason": "机械单步",
            "tasks": [{"role": "a", "task": "改一行"}],
        },
        user_message="写一份调研报告",
    )


def test_website_none_path_blocked_continuation_site_shaped():
    """用户「继续完成官网…」+ 建站形 call → 拦 none。"""
    assert website_none_path_blocked(
        {
            "playbook_id": "none",
            "playbook_none_reason": "手写补完剩余分区",
            "tasks": [
                {
                    "role": "前端",
                    "task": "继续写完官网剩余分区的 HTML/CSS/JS",
                }
            ],
        },
        user_message="继续完成官网剩余分区",
    )
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "playbook_none_reason": "手写补完",
            "tasks": [
                {"role": "前端", "task": "补全分区 HTML CSS 落地页"}
            ],
        },
        user_message="继续完成官网剩余分区",
    )
    assert name is None and reason is None
    assert err is not None
    assert "build_website" in err
    from agentcore.runtime.delegate.playbook_declaration import (
        declaration_reject_gate,
        is_website_none_rejected,
    )

    assert is_website_none_rejected(err)
    assert declaration_reject_gate(err) == "website"


def test_website_none_path_not_blocked_generic_project_continue():
    """「讨论继续完成项目的开发」+ 手写前后端/HTML 游戏 → 声明闸通过（法庭迷局误伤回归）。"""
    args = {
        "playbook_id": "none",
        "playbook_none_reason": "继续法庭迷局游戏开发",
        "tasks": [
            {
                "role": "后端工程师",
                "task": "实现案件状态机与证据 API",
            },
            {
                "role": "前端工程师",
                "task": "HTML5 画布与卡牌交互 UI",
            },
        ],
    }
    assert not website_none_path_blocked(
        args,
        user_message="讨论继续完成项目的开发",
    )
    name, reason, err = resolve_playbook_declaration(
        args,
        user_message="讨论继续完成项目的开发",
    )
    assert err is None
    assert name is None


def test_website_none_path_not_blocked_continuation_config():
    """用户「继续完成」+ 改超时配置（无建站形）→ 不拦。"""
    assert not website_none_path_blocked(
        {
            "playbook_id": "none",
            "playbook_none_reason": "改运行参数",
            "tasks": [
                {"role": "运维", "task": "把超时配置从 30s 调到 60s"}
            ],
        },
        user_message="继续完成",
    )


def test_website_none_path_not_blocked_continuation_doc_html_path():
    """续作讨论 + 文档整理含 .html 路径（无建站词）→ 不拦手写 none。"""
    assert not website_none_path_blocked(
        {
            "playbook_id": "none",
            "playbook_none_reason": "先整理文档再继续开发",
            "tasks": [
                {
                    "role": "文档",
                    "task": "整理 docs/原型打印卡牌.html 与相关说明",
                }
            ],
        },
        user_message="讨论继续完成开发、先对文档进行整理",
    )


def test_website_none_path_continuation_audit_still_exempt():
    """续派短句 + 审计框定 call → 豁免仍有效。"""
    assert not website_none_path_blocked(
        {
            "playbook_id": "none",
            "playbook_none_reason": "质量敏感成品独立审计",
            "tasks": [
                {
                    "role": "审计员",
                    "task": "对 GEO 官网的两个交付物进行独立审计并出报告",
                }
            ],
        },
        user_message="继续完成",
    )


def test_software_intent_skips_website_continuation_gate():
    """软件意图 + 非 site 绿场 → 建站续作闸不拦；薄 HTML 仍由软件闸拒。"""
    thin = {
        "playbook_id": "none",
        "playbook_none_reason": "单 HTML 即可",
        "tasks": [
            {"role": "前端工程师", "task": "写 app.html 单文件工具"},
        ],
    }
    # Website gate must not fire (software priority).
    assert not website_none_path_blocked(
        thin,
        user_message="帮我做一个思维导图软件，继续完成项目的开发",
    )
    # Software thin gate still rejects.
    name, reason, err = resolve_playbook_declaration(
        thin,
        user_message="帮我做一个思维导图软件，继续完成项目的开发",
    )
    assert name is None and reason is None
    assert err is not None
    assert "build_feature" in err
    from agentcore.runtime.delegate.playbook_declaration import declaration_reject_gate

    assert declaration_reject_gate(err) == "software"


async def test_execute_accepts_handwritten_without_playbook():
    """自由组队无声明：声明闸放行（后续可能因无 LLM 失败，但不因 playbook 拒）。"""
    t = tool(Provider([]))
    result = await t.execute(
        {
            "tasks": [{"role": "A", "task": "做一点"}],
        },
        ctx(),
    )
    # Must not be the old missing-declaration reject.
    assert "playbook_none_reason" not in (result.error or "")
    assert "须声明 playbook" not in (result.error or "")
    assert "声明必填" not in (result.error or "")


async def test_execute_rejects_website_none_bypass():
    t = tool(Provider([]))
    t._user_message = "请帮我搭建一个营销落地页"
    result = await t.execute(
        {
            "playbook_id": "none",
            "playbook_none_reason": "手写两阶段即可",
            "tasks": [
                {"role": "文案", "task": "写落地页文案"},
                {"role": "前端", "task": "实现落地页 HTML"},
            ],
        },
        ctx(),
    )
    assert result.success is False
    assert result.contract_failure is True
    assert "build_website" in (result.error or "")
    assert "none" in (result.error or "")


def test_software_intent_none_thin_html_rejected():
    """软件意图 + none + 单前端单 HTML → 拒（回归：思维导图软件压成单文件）。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "playbook_none_reason": "单 HTML 即可交付基础版",
            "tasks": [
                {
                    "role": "前端工程师",
                    "task": "写一个 mindmap.html 单文件思维导图工具",
                }
            ],
        },
        user_message="帮我做一个思维导图软件",
    )
    assert name is None and reason is None
    assert err is not None
    assert "build_feature" in err
    assert "优先" not in err
    assert "禁止" in err or "单" in err


def test_software_intent_named_build_feature_ok():
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook": "build_feature",
            "playbook_args": {"feature": "思维导图编辑器", "stack": "FastAPI+React"},
        },
        user_message="帮我做一个思维导图软件",
    )
    assert err is None
    assert name == "build_feature"
    assert reason is None


def test_software_intent_none_multi_role_with_reason_ok():
    """软件意图 + none + 多角色工程拆分 → 仍可（非薄路径；理由可选）。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "tasks": [
                {"role": "后端工程师", "task": "实现本地存储与同步 API"},
                {
                    "role": "前端工程师",
                    "task": "实现编辑器 UI，depends 后端契约",
                    "depends_on": ["api"],
                },
                {
                    "role": "测试工程师",
                    "task": "覆盖同步与编辑边界",
                    "depends_on": ["api"],
                },
            ],
        },
        user_message="帮我做一个笔记应用",
    )
    assert err is None
    assert name is None


def test_software_intent_none_user_confirmed_delivery_exempt():
    """开工卡已确认单页原型 → none+单前端可过（显式可观测理由）。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook_id": "none",
            "playbook_none_reason": "用户已确认交付形态为可运行单页原型",
            "tasks": [
                {
                    "role": "前端工程师",
                    "task": "交付 mindmap.html 单页原型",
                }
            ],
        },
        user_message="帮我做一个思维导图软件",
    )
    assert err is None
    assert name is None
    assert "用户已确认" in (reason or "")


def test_software_none_path_blocked_helper():
    assert software_none_path_blocked(
        {
            "playbook_none_reason": "单文件即可",
            "tasks": [
                {"role": "前端工程师", "task": "写 app.html"},
            ],
        },
        user_message="做一个待办软件",
    )
    assert not software_none_path_blocked(
        {
            "playbook_none_reason": "机械单步",
            "tasks": [{"role": "a", "task": "改一行"}],
        },
        user_message="把超时改成 30s",
    )


async def test_execute_rejects_software_thin_html_none():
    t = tool(Provider([]))
    t._user_message = "帮我做一个思维导图软件"
    result = await t.execute(
        {
            "playbook_id": "none",
            "playbook_none_reason": "单 HTML 基础版就够",
            "tasks": [
                {"role": "前端工程师", "task": "实现 mindmap.html"},
            ],
        },
        ctx(),
    )
    assert result.success is False
    assert result.contract_failure is True
    assert "build_feature" in (result.error or "")
    assert "优先" not in (result.error or "")
