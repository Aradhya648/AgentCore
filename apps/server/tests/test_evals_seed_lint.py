"""种子用例静态校验单测（评估体系 §十二）：零 LLM，可进 per-PR 硬门禁.

读纯静态路径（``seed_lint`` 只依赖 ``checks`` 注册表），不 import harness/runner（不拉 runtime）。
最关键的一条：**仓库里实际发布的 core 套件必须 lint 干净**——用例写错（拼错 check 名、漏字段、
非法 category）当场挂，挡在合并前。
"""

import json
from pathlib import Path

import agentcore.evals as ev
from agentcore.evals.seed_lint import lint_case, lint_suite

_CORE_DIR = Path(ev.__file__).parent / "cases" / "core"


def _load_core_raw() -> list[dict]:
    raws: list[dict] = []
    for path in sorted(_CORE_DIR.glob("*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            raws.extend(loaded)
        else:
            raws.append(loaded)
    return raws


def test_shipped_core_suite_lints_clean():
    raws = _load_core_raw()
    assert len(raws) >= 6, "core 种子套件应至少 6 例（§十三 倾向 6–8）"
    errors = lint_suite(raws)
    assert errors == [], f"core 套件 lint 不干净: {errors}"


def test_shipped_core_suite_covers_key_categories():
    cats = {r["category"] for r in _load_core_raw()}
    # 覆盖度自检：黄金集应跨类别（§七），别全堆在 qa
    for required in ("qa", "retrieval", "tool_use", "team", "routing", "no_fabrication"):
        assert required in cats, f"core 套件缺类别 {required!r}"


def test_lint_missing_required_field():
    errors = lint_case({"category": "qa", "user_message": "q", "checks": [{"name": "NonEmpty"}]})
    assert any("缺必填字段 'id'" in e for e in errors)


def test_lint_bad_category():
    errors = lint_case(
        {"id": "x", "category": "nope", "user_message": "q", "checks": [{"name": "NonEmpty"}]}
    )
    assert any("category" in e for e in errors)


def test_lint_unregistered_check_name():
    errors = lint_case(
        {"id": "x", "category": "qa", "user_message": "q", "checks": [{"name": "Nope"}]}
    )
    assert any("未注册" in e for e in errors)


def test_lint_no_checks_and_no_rubric():
    errors = lint_case({"id": "x", "category": "qa", "user_message": "q"})
    assert any("不会判定任何东西" in e for e in errors)


def test_lint_rubric_only_is_allowed():
    # 有 rubric（走裁判）即便没 checks 也合法
    errors = lint_case({"id": "x", "category": "qa", "user_message": "q", "rubric": "好不好"})
    assert errors == []


def test_lint_samples_must_be_positive():
    errors = lint_case(
        {
            "id": "x",
            "category": "qa",
            "user_message": "q",
            "checks": [{"name": "NonEmpty"}],
            "samples": 0,
        }
    )
    assert any("samples" in e for e in errors)


def test_lint_suite_flags_duplicate_ids():
    case = {"id": "dup", "category": "qa", "user_message": "q", "checks": [{"name": "NonEmpty"}]}
    errors = lint_suite([case, dict(case)])
    assert any("id 重复" in e for e in errors)
