"""Named-entity compare fanout gate unit tests."""

from agentcore.runtime.delegate.named_entity_fanout import (
    check_named_entity_fanout,
    extract_named_compare_entities,
)


def test_extract_db_triple():
    msg = (
        "帮我系统对比 PostgreSQL、MySQL、SQLite 三者在中小型 Web 项目里的取舍"
        "（性能、运维、生态、适用场景），最后给一份选型建议，写成 Markdown。"
    )
    assert extract_named_compare_entities(msg) == [
        "PostgreSQL",
        "MySQL",
        "SQLite",
    ]


def test_extract_frontend_stack():
    msg = (
        "我们要给内部工具选前端栈，请并行从「上手成本」「生态」「长期维护」三个角度"
        "分别评估 React、Vue、Svelte，再汇总一份选型备忘录。"
    )
    assert extract_named_compare_entities(msg) == ["React", "Vue", "Svelte"]


def test_extract_skips_unnamed_market_survey():
    msg = "调研市面三款产品，整理成对比表"
    assert extract_named_compare_entities(msg) == []


def test_reject_when_understaffed():
    msg = "系统对比 PostgreSQL、MySQL、SQLite 三者在中小型 Web 项目里的取舍"
    err = check_named_entity_fanout(
        {"tasks": [{"role": "研究员", "task": "写对比报告"}]},
        user_message=msg,
    )
    assert err is not None
    assert "至少派 3 人" in err
    assert "PostgreSQL" in err


def test_ok_when_enough_workers():
    msg = "系统对比 PostgreSQL、MySQL、SQLite 三者"
    err = check_named_entity_fanout(
        {
            "tasks": [
                {"role": "pg", "task": "摸 PG"},
                {"role": "my", "task": "摸 MySQL"},
                {"role": "lite", "task": "摸 SQLite"},
            ]
        },
        user_message=msg,
    )
    assert err is None


def test_force_bypasses():
    msg = "系统对比 PostgreSQL、MySQL、SQLite 三者"
    err = check_named_entity_fanout(
        {
            "force": True,
            "tasks": [{"role": "一人", "task": "全包"}],
        },
        user_message=msg,
    )
    assert err is None


def test_tasks_json_string_still_rejects():
    msg = "系统对比 PostgreSQL、MySQL、SQLite 三者"
    err = check_named_entity_fanout(
        {"tasks": '[{"role": "一人", "task": "全包"}]'},
        user_message=msg,
    )
    assert err is not None
    assert "至少派 3 人" in err


def test_playbook_path_skips():
    msg = "系统对比 PostgreSQL、MySQL、SQLite 三者"
    err = check_named_entity_fanout(
        {
            "playbook": "multi_lens_research",
            "playbook_args": {"topic": "db"},
        },
        user_message=msg,
    )
    assert err is None
