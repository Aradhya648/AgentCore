"""Consumer-missing-depends gate unit tests."""

from agentcore.runtime.delegate.consumer_deps import (
    check_consumer_missing_depends,
    task_claims_teammate_output,
)


def test_reject_goldbach_style_summarizer_empty_deps():
    """哥德巴赫三人：两调研 +「基于前两位队员的产出」汇总且空依赖 → 拒收。"""
    err = check_consumer_missing_depends(
        [
            {"id": "r1", "role": "调研甲", "task": "调研偶数哥德巴赫猜想相关文献"},
            {"id": "r2", "role": "调研乙", "task": "调研奇数哥德巴赫猜想相关文献"},
            {
                "id": "s",
                "role": "汇总",
                "task": "基于前两位队员的产出，整理一份综述报告",
            },
        ]
    )
    assert err is not None
    assert "汇总" in err
    assert "depends_on" in err
    assert "r1" in err
    assert "r2" in err
    assert "force=true" in err


def test_ok_when_depends_on_declared():
    err = check_consumer_missing_depends(
        [
            {"id": "r1", "role": "调研甲", "task": "调研 A"},
            {"id": "r2", "role": "调研乙", "task": "调研 B"},
            {
                "id": "s",
                "role": "汇总",
                "task": "基于前两位队员的产出写综述",
                "depends_on": ["r1", "r2"],
            },
        ]
    )
    assert err is None


def test_ok_independent_roles_without_teammate_cue():
    err = check_consumer_missing_depends(
        [
            {"id": "a", "role": "前端", "task": "实现登录页"},
            {"id": "b", "role": "后端", "task": "实现鉴权 API"},
            {"id": "c", "role": "测试", "task": "补集成测试用例"},
        ]
    )
    assert err is None


def test_force_bypasses():
    err = check_consumer_missing_depends(
        [
            {"id": "r1", "role": "调研甲", "task": "调研"},
            {
                "role": "汇总",
                "task": "基于前两位队员的产出写综述",
            },
        ],
        force=True,
    )
    assert err is None


def test_single_task_skips():
    err = check_consumer_missing_depends(
        [
            {
                "role": "写手",
                "task": "基于前两位队员的产出写综述",
            },
        ]
    )
    assert err is None


def test_public_report_cue_does_not_false_positive():
    """「基于公开报告」无队友指称 → 不误伤。"""
    assert not task_claims_teammate_output("基于公开报告写一份摘要")
    err = check_consumer_missing_depends(
        [
            {"id": "a", "role": "甲", "task": "收集公开资料"},
            {
                "id": "b",
                "role": "乙",
                "task": "基于公开报告写一份摘要",
            },
        ]
    )
    assert err is None


def test_null_and_empty_depends_both_count_as_empty():
    # missing key / explicit null / [] 都算空
    cases: list[dict | None] = [None, {"depends_on": None}, {"depends_on": []}]
    for extra in cases:
        task: dict = {
            "id": "s",
            "role": "汇总",
            "task": "综合上述调研给出结论",
        }
        if extra:
            task.update(extra)
        err = check_consumer_missing_depends(
            [
                {"id": "r1", "role": "调研", "task": "调研"},
                task,
            ]
        )
        assert err is not None, f"expected reject for extra={extra!r}"
        assert "汇总" in err
        assert "r1" in err


def test_suggests_role_when_peer_has_no_id():
    err = check_consumer_missing_depends(
        [
            {"role": "调研甲", "task": "调研"},
            {"role": "调研乙", "task": "调研"},
            {
                "role": "汇总写手",
                "task": "吃上游结论后出终稿",
                "depends_on": [],
            },
        ]
    )
    assert err is not None
    assert "汇总写手" in err
    assert "调研甲" in err
    assert "调研乙" in err


def test_english_based_on_previous_triggers():
    err = check_consumer_missing_depends(
        [
            {"id": "a", "role": "A", "task": "research X"},
            {
                "id": "b",
                "role": "B",
                "task": "Write a brief based on previous findings",
            },
        ]
    )
    assert err is not None
    assert "B" in err
    assert "a" in err
