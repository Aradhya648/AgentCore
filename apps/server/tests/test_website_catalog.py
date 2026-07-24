"""P1b built-in website section catalog — marketing + tool_dense packs."""

from __future__ import annotations

from agentcore.runtime.runs.playbooks import expand_playbook
from agentcore.runtime.runs.website_catalog import (
    CATALOG_POINTER_PREFIX,
    MARKETING_SECTION_IDS,
    PACK_MARKETING,
    PACK_TOOL_DENSE,
    TOOL_DENSE_POINTER_PREFIX,
    TOOL_DENSE_SECTION_IDS,
    assert_marketing_pack_complete,
    assert_tool_dense_pack_complete,
    get_marketing_section,
    get_pack_section,
    list_marketing_sections,
    list_tool_dense_sections,
    match_section_name,
    read_shell_html,
)


def test_marketing_pack_complete_and_ids():
    missing = assert_marketing_pack_complete()
    assert missing == [], f"missing catalog files: {missing}"
    assert len(MARKETING_SECTION_IDS) >= 8
    assert len(MARKETING_SECTION_IDS) <= 12
    expected = {
        "nav",
        "hero",
        "logos",
        "features",
        "how_it_works",
        "testimonials",
        "pricing",
        "faq",
        "cta",
        "footer",
    }
    assert set(MARKETING_SECTION_IDS) == expected
    for sid in MARKETING_SECTION_IDS:
        sec = get_marketing_section(sid)
        assert sec is not None
        assert sec.pointer.startswith(f"{CATALOG_POINTER_PREFIX}/")
        html = read_shell_html(sid)
        assert f'data-catalog="{sid}"' in html
        assert "var(--" in html


def test_tool_dense_pack_complete_and_ids():
    missing = assert_tool_dense_pack_complete()
    assert missing == [], f"missing tool_dense files: {missing}"
    expected = {
        "app_shell",
        "sidebar",
        "topbar",
        "page_header",
        "filter_bar",
        "data_table",
        "detail_panel",
        "empty_state",
    }
    assert set(TOOL_DENSE_SECTION_IDS) == expected
    assert list(TOOL_DENSE_SECTION_IDS) == [
        "app_shell",
        "sidebar",
        "topbar",
        "page_header",
        "filter_bar",
        "data_table",
        "detail_panel",
        "empty_state",
    ]
    for sid in TOOL_DENSE_SECTION_IDS:
        sec = get_pack_section(sid, pack=PACK_TOOL_DENSE)
        assert sec is not None
        assert sec.pack == PACK_TOOL_DENSE
        assert sec.pointer.startswith(f"{TOOL_DENSE_POINTER_PREFIX}/")
        html = read_shell_html(sid, pack=PACK_TOOL_DENSE)
        assert f'data-catalog="{sid}"' in html
        assert "var(--" in html
        assert "{{" in html


def test_match_section_name_defaults():
    assert match_section_name("首屏英雄区") is not None
    assert match_section_name("首屏英雄区").id == "hero"
    assert match_section_name("卖点能力区").id == "features"
    assert match_section_name("行动号召区").id == "cta"
    assert match_section_name("定价").id == "pricing"
    assert match_section_name("常见 FAQ").id == "faq"
    assert match_section_name("导航").id == "nav"
    assert match_section_name("完全无关的区块名xyz") is None


def test_match_section_name_tool_dense():
    assert match_section_name("应用外壳", pack=PACK_TOOL_DENSE).id == "app_shell"
    assert match_section_name("侧栏导航", pack=PACK_TOOL_DENSE).id == "sidebar"
    assert match_section_name("顶栏", pack=PACK_TOOL_DENSE).id == "topbar"
    assert match_section_name("页面标题区", pack=PACK_TOOL_DENSE).id == "page_header"
    assert match_section_name("筛选条", pack=PACK_TOOL_DENSE).id == "filter_bar"
    assert match_section_name("数据表格", pack=PACK_TOOL_DENSE).id == "data_table"
    assert match_section_name("详情面板", pack=PACK_TOOL_DENSE).id == "detail_panel"
    assert match_section_name("空状态", pack=PACK_TOOL_DENSE).id == "empty_state"
    assert match_section_name("sidebar", pack=PACK_TOOL_DENSE).id == "sidebar"
    # Marketing labels must not match tool pack
    assert match_section_name("首屏英雄区", pack=PACK_TOOL_DENSE) is None


def test_build_website_injects_catalog_pointers():
    tasks, errors = expand_playbook(
        "build_website",
        {
            "site": "Demo 落地页",
            "sections": ["首屏英雄区", "卖点能力区", "行动号召区"],
        },
    )
    assert errors == []
    by_id = {t["id"]: t for t in tasks}
    sk = by_id["skeleton"]["task"]
    assert f"pack={PACK_MARKETING}" in sk
    assert "catalog:hero" in sk
    assert f"{CATALOG_POINTER_PREFIX}/hero.html" in sk
    assert "catalog:features" in sk
    assert "catalog:cta" in sk
    assert "【禁止】临场另起 nav" in sk or "禁止】临场另起 nav" in sk
    assert "data-catalog=\"hero\"" in sk  # shell body embedded
    assert "var(--color-fg)" in sk or "var(--" in sk
    assert "catalog:_shared.css" in sk
    assert ".site-hero" in sk
    assert "CONTRACT 起步表" in sk
    assert "| s0 |" in sk
    assert f"pack={PACK_TOOL_DENSE}" not in sk

    s0 = by_id["section_0"]["task"]
    assert "catalog:hero" in s0
    assert f"{CATALOG_POINTER_PREFIX}/hero.html" in s0
    assert "禁止】另起 nav" in s0 or "【禁止】另起 nav" in s0

    s1 = by_id["section_1"]["task"]
    assert "catalog:features" in s1
    s2 = by_id["section_2"]["task"]
    assert "catalog:cta" in s2


def test_build_website_catalog_mapping_for_custom_labels():
    tasks, errors = expand_playbook(
        "build_website",
        {"site": "S", "sections": ["导航", "定价", "FAQ"]},
    )
    assert errors == []
    by_id = {t["id"]: t for t in tasks}
    sk = by_id["skeleton"]["task"]
    assert "catalog:nav" in sk
    assert "catalog:pricing" in sk
    assert "catalog:faq" in sk
    assert "website_catalog/marketing/pricing.html" in by_id["section_1"]["task"]
    assert "catalog:faq" in by_id["section_2"]["task"]


def test_build_toolshed_injects_tool_dense_pointers():
    tasks, errors = expand_playbook(
        "build_toolshed",
        {"site": "Ops", "sections": ["应用外壳", "筛选条", "空状态"]},
    )
    assert errors == []
    by_id = {t["id"]: t for t in tasks}
    sk = by_id["skeleton"]["task"]
    assert f"pack={PACK_TOOL_DENSE}" in sk
    assert "catalog:app_shell" in sk
    assert f"{TOOL_DENSE_POINTER_PREFIX}/filter_bar.html" in sk
    assert "catalog:empty_state" in sk
    assert "tool-app-shell" in sk
    assert "catalog:_shared.css" in sk
    assert f"pack={PACK_MARKETING}" not in sk
    assert "website_catalog/marketing/" not in sk


def test_list_marketing_sections_stable_order():
    ids = [s.id for s in list_marketing_sections()]
    assert ids == list(MARKETING_SECTION_IDS)


def test_list_tool_dense_sections_stable_order():
    ids = [s.id for s in list_tool_dense_sections()]
    assert ids == list(TOOL_DENSE_SECTION_IDS)


def test_catalog_shells_plus_shared_css_pass_web_seam():
    """Pasting shells + _shared.css must clear web_seam (GEO r3 skeleton failure mode)."""
    from agentcore.runtime.runs.web_seam import check_web_seam_failures
    from agentcore.runtime.runs.website_catalog import (
        read_shared_css,
        read_shell_html,
    )

    html = (
        "<!doctype html><html><body>"
        + read_shell_html("hero")
        + read_shell_html("features")
        + read_shell_html("cta")
        + "</body></html>"
    )
    css = read_shared_css()
    failures = check_web_seam_failures(
        {"site/index.html": html, "site/styles.css": css, "site/main.js": ""}
    )
    assert failures == [], failures


def test_tool_dense_shells_plus_shared_css_pass_web_seam():
    from agentcore.runtime.runs.web_seam import check_web_seam_failures
    from agentcore.runtime.runs.website_catalog import (
        read_shared_css,
        read_shell_html,
    )

    html = (
        "<!doctype html><html><body>"
        + read_shell_html("app_shell", pack=PACK_TOOL_DENSE)
        + read_shell_html("data_table", pack=PACK_TOOL_DENSE)
        + read_shell_html("empty_state", pack=PACK_TOOL_DENSE)
        + "</body></html>"
    )
    css = read_shared_css(pack=PACK_TOOL_DENSE)
    failures = check_web_seam_failures(
        {"site/index.html": html, "site/styles.css": css, "site/main.js": ""}
    )
    assert failures == [], failures
