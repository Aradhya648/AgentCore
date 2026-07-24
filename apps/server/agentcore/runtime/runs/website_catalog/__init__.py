"""Built-in website section catalog (P1b) — constraint input, not a second framework.

Marketing landing pack ships under ``website_catalog/marketing/`` (playbook
``build_website``). Tool-dense console pack ships under ``website_catalog/tool_dense/``
(playbook ``build_toolshed``). Briefs inject catalog id / path / summary (+ shell
body); scanner does **not** hard-gate "must have used a shell".
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

PACK_MARKETING = "marketing"
PACK_TOOL_DENSE = "tool_dense"

# Stable pointer prefixes for task briefs / tests (package-relative, not workspace).
CATALOG_POINTER_PREFIX = "website_catalog/marketing"
TOOL_DENSE_POINTER_PREFIX = "website_catalog/tool_dense"

_MARKETING_PACKAGE = "agentcore.runtime.runs.website_catalog.marketing"
_TOOL_DENSE_PACKAGE = "agentcore.runtime.runs.website_catalog.tool_dense"

_PACK_PACKAGES: dict[str, str] = {
    PACK_MARKETING: _MARKETING_PACKAGE,
    PACK_TOOL_DENSE: _TOOL_DENSE_PACKAGE,
}

_PACK_POINTER_PREFIX: dict[str, str] = {
    PACK_MARKETING: CATALOG_POINTER_PREFIX,
    PACK_TOOL_DENSE: TOOL_DENSE_POINTER_PREFIX,
}


@dataclass(frozen=True, slots=True)
class CatalogSection:
    """One section shell in a catalog pack."""

    id: str
    title: str
    summary: str
    html_name: str
    keywords: tuple[str, ...]
    pack: str = PACK_MARKETING

    @property
    def pointer(self) -> str:
        """Human/audit path: ``website_catalog/{pack}/{id}.html``."""
        prefix = _PACK_POINTER_PREFIX.get(self.pack, f"website_catalog/{self.pack}")
        return f"{prefix}/{self.html_name}"


# Canonical marketing pack — ids are the contract for tests + playbook injection.
_MARKETING_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection(
        id="nav",
        title="顶栏导航",
        summary="品牌字标 + 少量锚点链 + 主 CTA；克制横排，禁巨型 mega-menu。",
        html_name="nav.html",
        keywords=("nav", "导航", "顶栏", "header", "菜单"),
    ),
    CatalogSection(
        id="hero",
        title="首屏英雄区",
        summary="单一构图：品牌/主文案 + 短支持句 + 主 CTA；禁统计条/多卡堆叠。",
        html_name="hero.html",
        keywords=("hero", "首屏", "英雄", "banner", "着陆", "hero区"),
    ),
    CatalogSection(
        id="logos",
        title="信任 Logo 条",
        summary="一排灰度客户/媒体 logo 占位；少文案，不作卖点墙。",
        html_name="logos.html",
        keywords=("logo", "logos", "信任", "客户", "合作", "背书"),
    ),
    CatalogSection(
        id="features",
        title="卖点能力区",
        summary="2–4 个能力块；避免三等分 icon 卡八股，用稳定 id/class。",
        html_name="features.html",
        keywords=("feature", "features", "卖点", "能力", "功能", "亮点"),
    ),
    CatalogSection(
        id="how_it_works",
        title="使用步骤",
        summary="3 步以内流程；序号 + 短说明，禁装饰粒子背景。",
        html_name="how_it_works.html",
        keywords=("how", "步骤", "流程", "怎么用", "使用", "works"),
    ),
    CatalogSection(
        id="testimonials",
        title="用户证言",
        summary="1–3 条引用卡；有出处占位，禁假指标数字墙。",
        html_name="testimonials.html",
        keywords=("testimonial", "证言", "评价", "口碑", "案例", "quote"),
    ),
    CatalogSection(
        id="pricing",
        title="定价区",
        summary="2–3 档价卡；强调一档，CTA 指向行动，禁假「限时」堆叠。",
        html_name="pricing.html",
        keywords=("pricing", "定价", "价格", "套餐", "资费", "price"),
    ),
    CatalogSection(
        id="faq",
        title="常见问题",
        summary="details/summary 手风琴；问句短、答可核对，禁假拉丁填充。",
        html_name="faq.html",
        keywords=("faq", "问答", "常见问题", "问题"),
    ),
    CatalogSection(
        id="cta",
        title="行动号召区",
        summary="收束区：一句主张 + 主 CTA；可附次要链，勿再发明整站导航。",
        html_name="cta.html",
        keywords=("cta", "行动", "号召", "转化", "报名", "试用"),
    ),
    CatalogSection(
        id="footer",
        title="页脚",
        summary="版权 + 少量链；无真实联系方式则【不设】电话/备案/邮箱板块。",
        html_name="footer.html",
        keywords=("footer", "页脚", "底部", "copyright"),
    ),
)

# Tool-dense console pack (revisions 5–6) — dense chrome, not marketing skin.
_TOOL_DENSE_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection(
        id="app_shell",
        title="应用外壳",
        summary="外框：侧栏槽 + 主工作区槽；dense 布局，禁营销 hero 全幅首屏。",
        html_name="app_shell.html",
        keywords=("app_shell", "外壳", "应用框", "layout", "框架", "壳"),
        pack=PACK_TOOL_DENSE,
    ),
    CatalogSection(
        id="sidebar",
        title="侧栏导航",
        summary="产品字标 + 少量导航项；克制列表，禁巨型 mega-menu / 价卡。",
        html_name="sidebar.html",
        keywords=("sidebar", "侧栏", "侧边栏", "侧边", "nav"),
        pack=PACK_TOOL_DENSE,
    ),
    CatalogSection(
        id="topbar",
        title="顶栏",
        summary="面包屑 / 搜索 / 用户；矮 dense 顶栏，非营销横幅。",
        html_name="topbar.html",
        keywords=("topbar", "顶栏", "toolbar", "工具条", "面包屑"),
        pack=PACK_TOOL_DENSE,
    ),
    CatalogSection(
        id="page_header",
        title="页面标题区",
        summary="页标题 + 主/次操作；禁统计条与 hero 构图。",
        html_name="page_header.html",
        keywords=("page_header", "页头", "页面标题", "标题区", "header"),
        pack=PACK_TOOL_DENSE,
    ),
    CatalogSection(
        id="filter_bar",
        title="筛选条",
        summary="紧凑筛选控件横排；禁装饰粒子背景。",
        html_name="filter_bar.html",
        keywords=("filter", "filter_bar", "筛选", "过滤", "过滤器"),
        pack=PACK_TOOL_DENSE,
    ),
    CatalogSection(
        id="data_table",
        title="数据表格",
        summary="稳定列头与行 id；列表主区，禁假指标数字墙。",
        html_name="data_table.html",
        keywords=("data_table", "table", "表格", "列表", "数据表"),
        pack=PACK_TOOL_DENSE,
    ),
    CatalogSection(
        id="detail_panel",
        title="详情面板",
        summary="选中行详情；字段短文案，非营销证言卡。",
        html_name="detail_panel.html",
        keywords=("detail", "detail_panel", "详情", "面板", "抽屉"),
        pack=PACK_TOOL_DENSE,
    ),
    CatalogSection(
        id="empty_state",
        title="空状态",
        summary="短说明 + 主操作；禁假拉丁填充与营销 CTA 墙。",
        html_name="empty_state.html",
        keywords=("empty", "empty_state", "空态", "空状态", "无数据"),
        pack=PACK_TOOL_DENSE,
    ),
)

MARKETING_SECTION_IDS: tuple[str, ...] = tuple(s.id for s in _MARKETING_SECTIONS)
TOOL_DENSE_SECTION_IDS: tuple[str, ...] = tuple(s.id for s in _TOOL_DENSE_SECTIONS)

_PACK_SECTIONS: dict[str, tuple[CatalogSection, ...]] = {
    PACK_MARKETING: _MARKETING_SECTIONS,
    PACK_TOOL_DENSE: _TOOL_DENSE_SECTIONS,
}

_PACK_LABEL: dict[str, str] = {
    PACK_MARKETING: "营销",
    PACK_TOOL_DENSE: "工具台 dense",
}

_PACK_CHROME_FORBID: dict[str, str] = {
    PACK_MARKETING: "nav / button / 价卡",
    PACK_TOOL_DENSE: "sidebar / topbar / table / panel",
}


def _sections_for(pack: str) -> tuple[CatalogSection, ...]:
    try:
        return _PACK_SECTIONS[pack]
    except KeyError as exc:
        raise KeyError(f"unknown catalog pack: {pack!r}") from exc


def _package_for(pack: str) -> str:
    try:
        return _PACK_PACKAGES[pack]
    except KeyError as exc:
        raise KeyError(f"unknown catalog pack: {pack!r}") from exc


def marketing_pack_dir() -> Path:
    """Filesystem path to the marketing pack (tests / tooling)."""
    return Path(str(files(_MARKETING_PACKAGE)))


def tool_dense_pack_dir() -> Path:
    """Filesystem path to the tool_dense pack (tests / tooling)."""
    return Path(str(files(_TOOL_DENSE_PACKAGE)))


def list_marketing_sections() -> tuple[CatalogSection, ...]:
    return _MARKETING_SECTIONS


def list_tool_dense_sections() -> tuple[CatalogSection, ...]:
    return _TOOL_DENSE_SECTIONS


def list_pack_sections(pack: str = PACK_MARKETING) -> tuple[CatalogSection, ...]:
    return _sections_for(pack)


def get_marketing_section(section_id: str) -> CatalogSection | None:
    return get_pack_section(section_id, pack=PACK_MARKETING)


def get_pack_section(
    section_id: str, *, pack: str = PACK_MARKETING
) -> CatalogSection | None:
    sid = (section_id or "").strip().lower()
    for s in _sections_for(pack):
        if s.id == sid:
            return s
    return None


def read_shell_html(section_id: str, *, pack: str = PACK_MARKETING) -> str:
    """Load shell HTML body for injection / inspection."""
    sec = get_pack_section(section_id, pack=pack)
    if sec is None:
        raise KeyError(f"unknown {pack} catalog id: {section_id!r}")
    root = files(_package_for(pack))
    return root.joinpath(sec.html_name).read_text(encoding="utf-8")


def match_section_name(
    name: str, *, pack: str = PACK_MARKETING
) -> CatalogSection | None:
    """Map a playbook section label (zh/en) to the closest shell in ``pack``."""
    raw = (name or "").strip()
    if not raw:
        return None
    lowered = raw.casefold()
    best: CatalogSection | None = None
    best_len = 0
    for sec in _sections_for(pack):
        if sec.id == lowered or sec.title == raw:
            return sec
        for kw in sec.keywords:
            k = kw.casefold()
            if k and k in lowered and len(k) > best_len:
                best = sec
                best_len = len(k)
    return best


@lru_cache(maxsize=4)
def _index_lines(pack: str) -> str:
    lines = [
        f"· catalog:{s.id}（{s.pointer}）— {s.title}：{s.summary}"
        for s in _sections_for(pack)
    ]
    return "\n".join(lines)


def _mapping_line(section_name: str, sec: CatalogSection | None, *, pack: str) -> str:
    if sec is None:
        return (
            f"【{section_name}】→ 未精确匹配；从 pack={pack} 索引中选最接近壳"
            f"（仍须写入 CONTRACT 的 catalog id）"
        )
    return f"【{section_name}】→ catalog:{sec.id}（{sec.pointer}）"


def catalog_prompt_block_skeleton(
    sections: list[str], *, pack: str = PACK_MARKETING
) -> str:
    """Inject into skeleton task: pick empty shells; map each partition."""
    label = _PACK_LABEL.get(pack, pack)
    chrome = _PACK_CHROME_FORBID.get(pack, "基础 UI")
    mapping = "；".join(
        _mapping_line(name, match_section_name(name, pack=pack), pack=pack)
        for name in sections
    )
    return (
        f"【{label} section catalog · pack={pack}】"
        "骨架须从下列内置空壳**选自搭**（约束输入，非第二框架；壳为简单 HTML/CSS 片段）：\n"
        f"{_index_lines(pack)}\n"
        f"本站分区→catalog 映射：{mapping}。"
        "色值只用壳内 CSS 变量（var(--…)），取值只来自 site/DESIGN.md tokens，禁止散写 hex。"
        f"【禁止】临场另起 {chrome} 等基础 UI 壳；未列出的装饰结构也勿发明。"
        "CONTRACT.md 须为每个分区记下 catalog id 与指针路径。"
    )


def catalog_prompt_block_section(
    parts: list[str], *, pack: str = PACK_MARKETING
) -> str:
    """Inject into section worker: fill copy on the matched shell only."""
    chrome = _PACK_CHROME_FORBID.get(pack, "基础 UI")
    bits: list[str] = []
    for part in parts:
        sec = match_section_name(part, pack=pack)
        if sec is None:
            bits.append(
                f"【{part}】未精确匹配 catalog；在 pack={pack} 索引中选最接近壳后"
                f"只填文案/补丁，【禁止】另起 {chrome} 等基础 UI。"
            )
            continue
        bits.append(
            f"【{part}】须基于 catalog:{sec.id}（{sec.pointer}）—"
            f"{sec.summary}"
            f"只填文案与局部补丁；【禁止】另起 {chrome} 等基础 UI 壳。"
        )
    return "【catalog 指针】" + "".join(bits)


def catalog_shell_bodies_for_sections(
    sections: list[str], *, pack: str = PACK_MARKETING
) -> str:
    """Embed matched shell HTML so sandbox workers can paste without package I/O."""
    seen: set[str] = set()
    chunks: list[str] = []
    for name in sections:
        sec = match_section_name(name, pack=pack)
        if sec is None or sec.id in seen:
            continue
        seen.add(sec.id)
        body = read_shell_html(sec.id, pack=pack).strip()
        chunks.append(
            f"----- catalog:{sec.id} · {sec.pointer} -----\n"
            f"{body}\n----- end catalog:{sec.id} -----"
        )
    if not chunks:
        return ""
    return (
        "【catalog 空壳正文·供骨架粘贴】以下片段已含 CSS 变量占位；"
        "粘进对应 SECTION 标记对内，再交给分区 worker 填文案：\n"
        + "\n".join(chunks)
    )


def read_shared_css(*, pack: str = PACK_MARKETING) -> str:
    """Load pack ``_shared.css`` (token bridge + web_seam stubs)."""
    return (
        files(_package_for(pack)).joinpath("_shared.css").read_text(encoding="utf-8")
    )


def catalog_shared_css_for_skeleton(*, pack: str = PACK_MARKETING) -> str:
    """Embed ``_shared.css`` so skeleton can write styles without package I/O."""
    body = read_shared_css(pack=pack).strip()
    return (
        "【catalog _shared.css·须写入 styles.css】把下列内容完整并入 "
        f"`site/styles.css`（可追加 DESIGN :root token 映射；禁止删掉 class/id 选择器，"
        "否则 web_seam 会拦挂空壳）：\n"
        f"----- catalog:_shared.css -----\n{body}\n----- end catalog:_shared.css -----"
    )


def catalog_contract_stub(
    sections: list[str], *, pack: str = PACK_MARKETING
) -> str:
    """Minimal CONTRACT.md starter so skeleton has a pasteable artifact baseline."""
    prefix = _PACK_POINTER_PREFIX.get(pack, f"website_catalog/{pack}")
    lines = [
        "# CONTRACT",
        "",
        "骨架须 file_write 为 `site/CONTRACT.md`；可基于下表扩写交互约定。",
        "",
        "| SECTION | 分区名 | catalog id | 指针 |",
        "|---|---|---|---|",
    ]
    for i, name in enumerate(sections):
        sec = match_section_name(name, pack=pack)
        cid = sec.id if sec else "(选最接近)"
        pointer = sec.pointer if sec else f"{prefix}/?.html"
        lines.append(f"| s{i} | {name} | {cid} | `{pointer}` |")
    lines.append("")
    return "【CONTRACT 起步表·供骨架落盘】\n" + "\n".join(lines)


def assert_pack_complete(pack: str = PACK_MARKETING) -> list[str]:
    """Return missing file names (empty = ok). Used by tests."""
    root = files(_package_for(pack))
    missing: list[str] = []
    for sec in _sections_for(pack):
        if not root.joinpath(sec.html_name).is_file():
            missing.append(sec.html_name)
    if not root.joinpath("_shared.css").is_file():
        missing.append("_shared.css")
    return missing


def assert_marketing_pack_complete() -> list[str]:
    return assert_pack_complete(PACK_MARKETING)


def assert_tool_dense_pack_complete() -> list[str]:
    return assert_pack_complete(PACK_TOOL_DENSE)
