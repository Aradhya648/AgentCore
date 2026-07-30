"""交付前核验·轻层守卫（finish_guard）。

模型在某轮宣布 done（不再调工具、且有正文）时，:func:`~agentcore.runtime.engine.react_loop`
不立刻接受，先过这道纯代码轻层守卫：扫产物的*可观测信号*，命中即返回锚定具体事实的
「待修正项」，由 loop 拼成系统提示注入、回炉一轮，而非照发。

这是 ReAct「唯一终止信号 = 模型自报 done」的**对称解**——给「交付前先核一道」一个不依赖
模型自觉、不经 CEO 判断的决定论闸门（CEO captain 与 worker 跑同一个 react_loop，故一处
落点同时盖住两条路）。本模块只产出结论与注入文案，保持纯函数、可独立单测，处置（回炉 /
放行 / 计数）在 react_loop 里。

轻层现覆盖三类**纯机械、近零误报**的校验：

1. **造引用拦截**——双轨：
   - 池序角标 ``[n]`` 指向不存在的来源卡（编号 < 1 或 > 来源数）；仅 CEO 路径开
     （``check_citations``）。
   - 台账 id ``#rN`` 必须 ∈ 本回合成稿可引用集（``deep_read ∪ selected``）；仅当正文出现约定
     ``#rN`` 标记时启用（Q5）；CEO / 调研 worker 在接通 ``citable_ids``（实为 draft 子集）时均查。
     另：书目著录形态绑定 ``#rN`` 时须 deep_read，且不得把开题/答辩/公告类元数据当学位论文；
     GB/T ``[D]/[J]`` 等类型标若同段无任何 ``#rN`` 亦回炉（拦编造著录）。
2. **结构完整性**——代码围栏未闭合（``` 开了没收尾、后文整片被当代码渲染）、或声明了语言却
   空体（标了 ``python`` 却没有任何内容，等于「答应给代码却没给」）。都是「交付不完整」的
   机械信号，最终交付里几乎不会有意为之，故误报率近零。
    3. **交付验收对照**（仅 CEO：``check_citations`` + 本回合已发射的 ``delivery_verdict``）——
       ``state=blocked`` 且无落盘时，正文不得宣称「已生成 / 已落盘 / 请下载」；
       ``state`` 为 ``blocked`` / ``partial``（有 blocking 缺口）时，不得宣称「全部完成 /
       全部就绪 / 全部交付」等全员成功话术，也不得宣称「已完整可用」等与卡冲突的完整可用句式，
       也不得宣称「已修好 / 验证通过 / 已跑通」等与卡冲突的修码完成话术，
       也不得宣称闭集「已完成交付 / 交付完成…」或「站点/网站/页面…做好了」等与卡冲突的交付完成话术
       （经 ``_claims_*`` + 否定前缀豁免；裸「已交付」不升到有文件闸，新词不进无否定空盘闸）；
       有交付卡且落地仅为 md/脚本等、无 ``.pptx``
       时，不得宣称「PPT 已落盘 / 可直接打开」；有交付卡时终稿超
       ``engine_ceo_overview_max_chars`` → 回炉压缩为概览（细节在卡 / run 详情）。

刻意**不**纳入「残留 TODO / 填空占位」之类：法律垂直会正当地在合同模板留空待填、worker 也会
如实写「该资料待客户提供」，机械判会误伤——轻层的立身之本是近零误报，宁缺毋滥。后续轻层（如
受限的 JSON 可解析）与重层（要跑 / 要重算 / 换眼睛找漏 / 回源对照）在此扩展。

**统一底线**：结构完整性两查对 CEO 与 worker 同样成立，二者收尾都过这道关（worker 回炉经
``run_output_reset`` 干净重写其卡片）；``[n]`` 造引用查仅 CEO 路径开；``#rN`` id 存在闸按
Q5 条件启用（见上）；交付验收对照（含概览篇幅）仅 CEO 路径开。

→ 见设计: docs/03-AI核心/执行引擎架构设计.md（ReAct 循环 · 交付前核验）
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agentcore.runtime.citations import (
    extract_ledger_ref_ids,
    invalid_ledger_ref_ids,
    out_of_range_markers,
)
from agentcore.runtime.evidence_ledger import is_announcement_doc_kind

if TYPE_CHECKING:
    from agentcore.runtime.delegate.delivery_status import DeliveryVerdict

# 学位论文 / 期刊式著录形态（与 #rN 同段出现时触发书目形态闸）。
_BIBLIO_FORM_RE = re.compile(
    r"\[D\]|\[J\]|\[M\]|\[C\]|\[N\]|学位论文|期刊论文|硕士论文|博士论文"
)
# 强 GB/T 文献类型标（近零误报）：无 #rN 绑定时视为未核验/编造著录。
_BIBLIO_TYPE_MARKER_RE = re.compile(r"\[(?:D|J|M|C|N)\]")

# CEO false-completion claims when delivery_status is blocked with no landed files.
# Near-zero FP: only fire with an explicit success claim, never on acknowledgment alone.
_BLOCKED_EMPTY_DELIVERY_CLAIMS = re.compile(
    r"(已生成|文件已|已落盘|已交付|已写入工作区|已存在于工作区|"
    r"可以(?:在|到)[^。\n]{0,40}文件[^。\n]{0,24}面板|"
    r"请(?:直接)?下载|下载该文件|下载后用)"
)

# All-success claims when delivery_status is blocked/partial (blocking gaps present).
# Prefer「全部/均已/都已」over bare「已就绪」to avoid FP on honest partial acknowledgments.
# 「已全部收卷」与 closing_posture A 姿势同源（cef27dfa 误报面）。
_ALL_SUCCESS_CLAIMS = re.compile(
    r"已全部收卷|全部收卷|已收卷|"
    r"已全部(?:完成|交付|就位|成功|就绪)|"
    r"全部(?:完成|交付|就位|成功|就绪)|"
    r"均已(?:完成|交付|就绪|成功|落盘)|"
    r"都已(?:完成|交付|就绪|成功)|"
    r"所有(?:任务|队员|节点)(?:已|都已)(?:完成|交付|就绪)"
)

# 可用性诚实性 · 与卡矛盾的窄闸（甲所需，非全面禁吹二期）：
# blocked/partial 时拦「已完整可用 / 已可以使用」等与交付卡冲突的完整可用宣称。
_FULLY_USABLE_CLAIMS = re.compile(
    r"(?:"
    r"已完整可用|已可以使用|已经可以使用|"
    r"已完全可用|已可直接使用|已经可以直接使用|"
    r"质检[^。\n]{0,12}已完整可用|"
    r"(?:面板|站点|页面|产物)[^。\n]{0,16}已完整可用"
    r")"
)

# 乙 · 与卡矛盾的修好/验绿宣称（窄闸，非全面禁可用类话术二期）：
# blocked/partial 时拦「已修好 / 验证通过 / 已跑通」等修码完成话术。
_FIXED_OR_VERIFIED_CLAIMS = re.compile(
    r"(?:"
    r"已修好|修复已完成|bug\s*已修复|缺陷已修复|问题已修复|"
    r"已验证通过|验证通过|验证已绿|验证已通过|"
    r"测试已通过|已跑通测试|测试已跑通"
    r")"
)

# 交付完成闭集 + 站点族「做好了」（窄闸）：blocked/partial 时拦与卡冲突的交付完成话术。
# 仅经 _claims_* + 否定前缀豁免；故意不拦裸「已交付/已经交付」、弱「可用」；新词不进空盘闸。
# 与 closing_posture A 姿势对齐（含收卷）。
_DELIVERY_DONE_CLAIMS = re.compile(
    r"(?:"
    r"已完成交付|交付已完成|完成交付|交付完成|已经交付完成|"
    r"已全部收卷|全部收卷|已收卷|"
    r"(?:站点|网站|页面)[^。\n]{0,16}(?:做好了|已做好)"
    r")"
)

# PPT / 幻灯片「已可打开」类断言：有交付卡且落地文件无 .pptx 时拦（仅 md/脚本 ≠ PPT 已交付）。
# 要求句内同时出现 PPT 语义 + 完成/可打开话术，避免「代码可直接使用」误伤。
_PPTX_READY_CLAIMS = re.compile(
    r"(?:"
    r"(?:PPTX?|幻灯片|课件|演示文稿)[^。\n]{0,32}"
    r"(?:已落盘|已生成|已交付|已就绪|已写入|已存在于工作区|"
    r"可(?:以)?(?:直接)?(?:使用|打开|下载)|请(?:直接)?(?:打开|下载|使用))"
    r"|"
    r"(?:可(?:以)?(?:直接)?(?:打开|使用|下载)|请(?:直接)?(?:打开|下载|使用)|下载后用)"
    r"[^。\n]{0,32}(?:PPTX?|幻灯片|课件|演示文稿)"
    r")",
    re.IGNORECASE,
)

_GAP_NEGATION_PREFIXES = ("尚未", "没有", "并未", "未", "没", "无")


def finish_guard(
    content: str,
    *,
    citation_count: int,
    check_citations: bool = True,
    citable_ids: frozenset[str] | set[str] | None = None,
    ledger_entries: list[dict] | None = None,
    delivery_verdict: DeliveryVerdict | None = None,
    overview_max_chars: int | None = None,
) -> list[str]:
    """模型宣布 done 时的轻层守卫：返回「待修正项」列表，空列表 = 放行交付。

    每条都是一句锚定具体事实的修正指令（镜像 ``loop_controller`` 的注入风格——锚到可观测
    的实事而非空泛的「再想想」），由 react_loop 经 :func:`format_guard_steer` 拼成系统
    提示注入、回炉一轮。纯函数、不经 LLM、不靠 CEO 自觉，可独立单测。

    这是**所有 react_loop 收尾共过的统一底线**——CEO captain 与 worker 都在 done 点过此关。
    现查三类，适用面不同：

    1. **造引用**：
       - ``[n]``（仅 ``check_citations``）：越界角标 → 编造引用。
       - ``#rN``（``citable_ids`` 非 None 且正文出现标记）：id ∉ 成稿可引用集
         （``deep_read ∪ selected``）→ 回炉项。
       - 书目形态 + 公告启发式（有 ``ledger_entries`` 时）：见 :func:`_bibliography_reworks`
         （含无 #rN 绑定的 GB/T ``[D]/[J]`` 著录）。
    2. **结构完整性**（始终查）：:func:`_code_fence_reworks`。
    3. **交付验收对照**（仅 ``check_citations``）：
       - 完成态互斥 A∪C（不依赖 ``delivery_verdict``）：同条不得既「请确认」又「已全部收卷」；
       - 有 ``delivery_verdict`` 时另拦假完成 / 全员成功 / 交付完成闭集等与卡矛盾话术；
       - 有交付卡时的概览篇幅（``overview_max_chars``，默认读设置）。
    """
    reworks: list[str] = []
    if check_citations:
        stray = out_of_range_markers(content, citation_count)
        if stray:
            marks = "、".join(f"[{n}]" for n in stray)
            reworks.append(
                f"正文用了 {marks} 这些来源角标，但本回合实际只有 {citation_count} 条来源——"
                "它们指向不存在的来源卡，属于编造引用（违反「绝不编造引用」）。请删除这些角标、"
                "改成真实存在的来源编号，或为该论断补上可检索到的来源；没有依据就直接去掉这处引用。"
            )
    reworks.extend(
        citation_quality_reworks(
            content,
            citable_ids=citable_ids,
            ledger_entries=ledger_entries,
        )
    )
    reworks.extend(_code_fence_reworks(content))
    if check_citations:
        # 完成态互斥（A∪C）：不依赖 delivery_verdict——单段正文自相矛盾即回炉。
        from agentcore.runtime.closing_posture import mutual_exclusion_rework

        conflict = mutual_exclusion_rework(content)
        if conflict:
            reworks.append(conflict)
        reworks.extend(_delivery_claim_reworks(content, delivery_verdict))
        reworks.extend(
            _overview_length_reworks(
                content,
                delivery_verdict,
                overview_max_chars=overview_max_chars,
            )
        )
    return reworks


def citation_quality_reworks(
    content: str,
    *,
    citable_ids: frozenset[str] | set[str] | None = None,
    ledger_entries: list[dict] | None = None,
) -> list[str]:
    """``#rN`` 合法性 + 书目形态闸（chat ``finish_guard`` 与文件合同闸共用）。

    ``ledger_entries is None`` → 书目闸关闭；空列表仍开通 unbound ``[D]/[J]`` 检查。
    ``citable_ids is None`` → 跳过非法 ``#rN`` 检查。
    """
    reworks: list[str] = []
    bad_refs = invalid_ledger_ref_ids(content, citable_ids)
    if bad_refs:
        marks = "、".join(bad_refs)
        reworks.append(
            f"正文用了 {marks} 这些台账引用来源，但它们不在本回合成稿可引用集中"
            "（须 deep_read 或 selected；search-only / 伪造 / 越界均不可）。"
            "请改成提示中「已登记来源」里成稿可引的 #rN，"
            "或先 read_url 深读后再引用；没有依据就直接去掉这处引用。"
        )
    reworks.extend(_bibliography_reworks(content, ledger_entries))
    return reworks


def _bibliography_bound_ref_ids(content: str) -> list[str]:
    """正文中与学位论文/期刊式著录同段绑定的 ``#rN``（首次出现序）。"""
    if not content or not content.strip():
        return []
    if not _BIBLIO_FORM_RE.search(content):
        return []
    refs = extract_ledger_ref_ids(content)
    if not refs:
        return []
    # 同段：按空行切段；段内同时有书目形态与 #rN 才算绑定。
    bound: list[str] = []
    seen: set[str] = set()
    for para in re.split(r"\n\s*\n", content):
        if not _BIBLIO_FORM_RE.search(para):
            continue
        for eid in extract_ledger_ref_ids(para):
            if eid not in seen:
                seen.add(eid)
                bound.append(eid)
    # 无空行分段时：整篇有书目形态 + 任意 #rN 视为绑定（近零漏报）。
    if not bound and _BIBLIO_FORM_RE.search(content):
        return refs
    return bound


def _unbound_bibliography_reworks(content: str) -> list[str]:
    """GB/T ``[D]/[J]/…`` 著录未绑任何 ``#rN`` → 回炉（拦编造学位论文式引用）。"""
    if not content or not content.strip():
        return []
    if not _BIBLIO_TYPE_MARKER_RE.search(content):
        return []
    unbound_paras: list[str] = []
    for para in re.split(r"\n\s*\n", content):
        if not _BIBLIO_TYPE_MARKER_RE.search(para):
            continue
        if extract_ledger_ref_ids(para):
            continue
        # 取段内首个类型标作锚，便于模型定位。
        m = _BIBLIO_TYPE_MARKER_RE.search(para)
        unbound_paras.append(m.group(0) if m else "[D]")
    if not unbound_paras:
        # 无空行分段：整篇有类型标且全文无任何 #rN。
        if not extract_ledger_ref_ids(content):
            marks = sorted({m.group(0) for m in _BIBLIO_TYPE_MARKER_RE.finditer(content)})
            return [
                "正文出现学位论文/期刊式著录标记（"
                + "、".join(marks)
                + "）但未就地绑定本回合台账 #rN——"
                "属于未核验或编造引用。请改为「已登记来源」中的 #rN（须 deep_read），"
                "或删除该书目式表述；禁止占位/巧合叙事。"
            ]
        return []
    marks_joined = "、".join(dict.fromkeys(unbound_paras))
    return [
        f"正文以 {marks_joined} 等著录形态写了文献条目，但同段未绑定任何台账 #rN——"
        "属于未核验或编造引用。请就地补上成稿可引的 #rN（须 deep_read），"
        "或删除该书目式表述；禁止占位/巧合叙事。"
    ]


def _bibliography_reworks(
    content: str, ledger_entries: list[dict] | None
) -> list[str]:
    """书目形态闸：无绑定 #rN 的 GB/T 著录；著录式绑定须 deep_read；禁公告当学位论文。"""
    if ledger_entries is None:
        return []
    reworks = _unbound_bibliography_reworks(content)
    bound = _bibliography_bound_ref_ids(content)
    if not bound:
        return reworks
    by_id = {
        str(e.get("id") or ""): e
        for e in ledger_entries
        if isinstance(e, dict) and e.get("id")
    }
    need_deep: list[str] = []
    announcements: list[str] = []
    for eid in bound:
        entry = by_id.get(eid)
        if entry is None:
            continue
        if not entry.get("deep_read"):
            need_deep.append(eid)
            continue
        if is_announcement_doc_kind(
            str(entry.get("doc_kind") or ""),
            title=str(entry.get("title") or ""),
            snippet=str(entry.get("snippet") or ""),
        ):
            announcements.append(eid)
    if need_deep:
        marks = "、".join(need_deep)
        reworks.append(
            f"正文以学位论文/期刊式著录绑定了 {marks}，但这些来源尚未 deep_read——"
            "请先 read_url 深读后再用著录形态引用，或删除该书目式表述与 #rN。"
        )
    if announcements:
        marks = "、".join(announcements)
        reworks.append(
            f"正文以学位论文/期刊式著录绑定了 {marks}，但台账元数据呈开题/答辩/公告类——"
            "不得把公告/开题材料当作学位论文或期刊论文著录。请改写出处表述，"
            "或换用深读后的正式文献；禁止占位/巧合叙事。"
        )
    return reworks


def _resolve_overview_max_chars(explicit: int | None) -> int:
    """``explicit`` wins for tests; else ``engine_ceo_overview_max_chars`` (≤0 = off)."""
    if explicit is not None:
        return int(explicit)
    from agentcore.config import settings

    return int(settings.engine_ceo_overview_max_chars or 0)


def _overview_length_reworks(
    content: str,
    delivery_verdict: DeliveryVerdict | None,
    *,
    overview_max_chars: int | None = None,
) -> list[str]:
    """C2：有交付卡时终稿须为短概览；超阈值则回炉（字数是「未复述 UI」的近零误报代理）。"""
    if delivery_verdict is None:
        return []
    if not content or not content.strip():
        return []
    limit = _resolve_overview_max_chars(overview_max_chars)
    if limit <= 0:
        return []
    n = len(content.strip())
    if n <= limit:
        return []
    return [
        f"本回合已发出交付状态卡（细节在交付卡 / 产物卡 / run 详情）——"
        f"终稿应是简短概览，当前约 {n} 字，超过上限 {limit} 字。"
        "请压缩为：结论与影响 → 看哪里（点路径/卡片，勿展开模块清单或工作日志）→ "
        "缺口与下一步（有则点名）。禁止复述各 worker 全文或重做状态大表。"
    ]


def _claims_fully_usable(content: str) -> bool:
    """True when prose asserts full usability, ignoring negated forms (尚未可用…)."""
    for match in _FULLY_USABLE_CLAIMS.finditer(content):
        start = match.start()
        prefix = content[max(0, start - 2) : start]
        if any(prefix.endswith(neg) for neg in _GAP_NEGATION_PREFIXES):
            continue
        return True
    return False


def _claims_fixed_or_verified(content: str) -> bool:
    """True when prose asserts fix/verify-green done, ignoring negated forms (尚未修好…)."""
    for match in _FIXED_OR_VERIFIED_CLAIMS.finditer(content):
        start = match.start()
        prefix = content[max(0, start - 2) : start]
        if any(prefix.endswith(neg) for neg in _GAP_NEGATION_PREFIXES):
            continue
        return True
    return False


def _claims_delivery_done(content: str) -> bool:
    """True when prose asserts delivery-done / site-ready, ignoring negated forms."""
    for match in _DELIVERY_DONE_CLAIMS.finditer(content):
        start = match.start()
        prefix = content[max(0, start - 2) : start]
        if any(prefix.endswith(neg) for neg in _GAP_NEGATION_PREFIXES):
            continue
        return True
    return False


def _claims_all_success(content: str) -> bool:
    """True when prose asserts full-team success, ignoring negated forms (尚未全部…)."""
    for match in _ALL_SUCCESS_CLAIMS.finditer(content):
        start = match.start()
        # 「已全部…」is always a positive claim.
        if content.startswith("已全部", start):
            return True
        prefix = content[max(0, start - 2) : start]
        if any(prefix.endswith(neg) for neg in _GAP_NEGATION_PREFIXES):
            continue
        return True
    return False


def _has_landed_pptx(delivered_files: tuple[str, ...]) -> bool:
    return any(str(path).lower().endswith(".pptx") for path in delivered_files)


def _claims_pptx_ready(content: str) -> bool:
    """True when prose asserts a PPT/slide deck is landed / openable (ignores 尚未…)."""
    for match in _PPTX_READY_CLAIMS.finditer(content):
        start = match.start()
        prefix = content[max(0, start - 2) : start]
        if any(prefix.endswith(neg) for neg in _GAP_NEGATION_PREFIXES):
            continue
        return True
    return False


def _delivery_claim_reworks(
    content: str,
    delivery_verdict: DeliveryVerdict | None,
) -> list[str]:
    """Reject false completion prose when the batch delivery card shows blocking gaps."""
    if delivery_verdict is None:
        return []
    if not content or not content.strip():
        return []
    state = delivery_verdict.state
    reworks: list[str] = []

    # PPT honesty: landed files exist but none are .pptx → no「PPT 已落盘 / 可打开」.
    # Empty landing stays on the blocked-empty gate above; this covers md/脚本伪完成.
    landed_files = delivery_verdict.delivered_files
    if (
        landed_files
        and not _has_landed_pptx(landed_files)
        and _claims_pptx_ready(content)
    ):
        landed = "、".join(landed_files)
        reworks.append(
            "本回合交付状态卡显示落地文件中没有 .pptx"
            f"（当前：{landed}）——"
            "正文不得宣称 PPT / 幻灯片 / 课件已落盘、可直接使用或可打开。"
            "请改为承认尚未交付 PowerPoint 文件，点名已有产物（如 md / 生成脚本）与缺口，"
            "并给出下一步（绑定本地目录运行脚本、或继续委派生成 .pptx）；"
            "不要用「PPT 已就绪」话术盖过部分交付。"
        )

    if state not in ("blocked", "partial"):
        return reworks

    # Narrow: blocked + zero files → no「已生成/请下载」file-delivery claims.
    if (
        state == "blocked"
        and not delivery_verdict.delivered_files
        and _BLOCKED_EMPTY_DELIVERY_CLAIMS.search(content)
    ):
        reworks.append(
            "本回合交付验收为「未满足」且工作区没有落盘文件（见交付状态卡）——"
            "正文不得宣称已生成 / 已落盘 / 已在工作区 / 请下载。"
            "请改为承认未交付，说明缺口，并给出用户可采取的下一步"
            "（例如绑定本地目录、或继续让团队用写文件工具落盘）；不要用完成话术盖过红卡。"
        )
    # Broader (C1): any blocking gaps → no「全部完成/全部就绪」all-success narrative.
    if _claims_all_success(content):
        label = "未满足" if state == "blocked" else "部分未满足"
        reworks.append(
            f"本回合交付验收为「{label}」（见交付状态卡，仍有 blocking 缺口）——"
            "正文不得宣称全部完成 / 全部就绪 / 全部交付 / 均已完成。"
            "请点名说明缺口与影响，再写简短概览；不要用全员成功话术盖过验收卡。"
        )
    # 可用性诚实性 · 与卡矛盾窄闸：blocked/partial 不得写「已完整可用」类。
    if _claims_fully_usable(content):
        label = "未满足" if state == "blocked" else "部分未满足"
        reworks.append(
            f"本回合交付验收为「{label}」（见交付状态卡，仍有 blocking 缺口）——"
            "正文不得宣称已完整可用 / 已可以使用 / 已可直接使用。"
            "请以交付状态卡为主答：点名缺口与待办，散文只作注释；不要用完整可用话术盖过红卡。"
        )
    # 乙 · 与卡矛盾的修好/验绿窄闸：blocked/partial 不得写「已修好 / 验证通过」类。
    if _claims_fixed_or_verified(content):
        label = "未满足" if state == "blocked" else "部分未满足"
        reworks.append(
            f"本回合交付验收为「{label}」（见交付状态卡，仍有 blocking 缺口）——"
            "正文不得宣称已修好 / 修复已完成 / 验证通过 / 测试已通过 / 已跑通。"
            "请以交付状态卡为主答：点名未过验收的缺口，散文只作注释；"
            "不要用修码完成或验绿话术盖过红卡。"
        )
    # 交付完成闭集 / 站点做好了：blocked/partial 不得写与卡冲突的交付完成话术。
    if _claims_delivery_done(content):
        label = "未满足" if state == "blocked" else "部分未满足"
        reworks.append(
            f"本回合交付验收为「{label}」（见交付状态卡，仍有 blocking 缺口）——"
            "正文不得宣称已完成交付 / 交付完成 / 已全部收卷 / 站点（网站/页面）做好了。"
            "请以交付状态卡为主答：点名缺口与待办，散文只作注释；"
            "不要用交付完成话术盖过红卡。"
        )
    return reworks


def _code_fence_reworks(content: str) -> list[str]:
    """结构完整性轻检：扫 Markdown 代码围栏，抓两类纯机械、近零误报的缺陷。

    - **未闭合**：``` 开了块却没收尾——会让后文整片被当代码渲染（最终交付里几乎不会有意为之）。
    - **声明语言却空体**：``` 标了语言（如 ``python``）却没有任何内容，等于「答应给代码却没给」。

    单遍扫行、把每个行首 ``` 当作开/合切换（标准 Markdown 同字符围栏不嵌套），开块时记下语言、
    累计块内非空内容；合块时若「有语言且零内容」记一条空体项，扫完仍在块内记一条未闭合项。
    措辞锚到具体缺陷并点明下一步，与造引用项同风格。
    """
    reworks: list[str] = []
    in_fence = False
    fence_lang = ""
    body_chars = 0
    for line in content.splitlines():
        if line.lstrip().startswith("```"):
            if in_fence:
                if fence_lang and body_chars == 0:
                    reworks.append(
                        f"正文里标注为「{fence_lang}」的代码块是空的——声明了代码却没有任何内容。"
                        "请补全该代码块的内容，或删除这个空代码块。"
                    )
                in_fence = False
                fence_lang = ""
                body_chars = 0
            else:
                in_fence = True
                fence_lang = line.lstrip().lstrip("`").strip()
                body_chars = 0
        elif in_fence and line.strip():
            body_chars += len(line.strip())
    if in_fence:
        reworks.append(
            "正文里有一个用 ``` 开启的代码块没有闭合（缺少结尾的 ```）——会导致后面的内容"
            "全部被当作代码渲染。请补上结尾的 ```，或删除多余的起始标记。"
        )
    return reworks


def format_guard_steer(reworks: list[str]) -> str:
    """把待修正项拼成一条注入模型的系统提示（空列表 → 空串）。

    镜像 ``loop_controller`` 各 steer 的「``[系统提示]`` + 锚定事实」风格：陈述查出的具体
    问题、点明下一步（改正或补来源），不空泛说教。由 react_loop append 进真实窗口、回炉
    一轮——故措辞允许模型继续调检索工具补依据，而非强制只能改写正文。

    因这条以 ``role="user"`` 进窗口（reasoner 靠一条 user 轮可靠触发下一步动作），模型易把它
    当成用户在纠错、回一句「谢谢指正，我重新整理」——而那句寒暄会随正常旁白通道漏进可见交付
    （真实事故）。故文案显式自证「系统自动核验、非用户反馈」并禁止致谢/复述/寒暄；共享基座提示词
    的 ``<system_feedback>`` 段对所有 ``[系统提示]`` 注入做同一约束（见 resolve/prompt.py）。
    """
    if not reworks:
        return ""
    items = "\n".join(f"- {r}" for r in reworks)
    return (
        "[系统提示] 交付前核验未通过（系统自动核验，非用户反馈），发现以下问题：\n"
        f"{items}\n"
        "请直接修正正文后再给出最终答案；如需补充依据，可继续调用检索工具后再作答。"
        "不要为此道谢、复述或寒暄，直接改。"
    )
