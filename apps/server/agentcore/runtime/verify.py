"""交付前核验·轻层守卫（finish_guard）。

模型在某轮宣布 done（不再调工具、且有正文）时，:func:`~agentcore.runtime.engine.react_loop`
不立刻接受，先过这道纯代码轻层守卫：扫产物的*可观测信号*，命中即返回锚定具体事实的
「待修正项」，由 loop 拼成系统提示注入、回炉一轮，而非照发。

这是 ReAct「唯一终止信号 = 模型自报 done」的**对称解**——给「交付前先核一道」一个不依赖
模型自觉、不经 CEO 判断的决定论闸门（CEO captain 与 worker 跑同一个 react_loop，故一处
落点同时盖住两条路）。本模块只产出结论与注入文案，保持纯函数、可独立单测，处置（回炉 /
放行 / 计数）在 react_loop 里。

轻层现覆盖两类**纯机械、近零误报**的校验：

1. **造引用拦截**——双轨：
   - 池序角标 ``[n]`` 指向不存在的来源卡（编号 < 1 或 > 来源数）；仅 CEO 路径开
     （``check_citations``）。
   - 台账 id ``#rN`` 必须 ∈ 本回合可引用台账（``citable=true``）；仅当正文出现约定
     ``#rN`` 标记时启用（Q5）；CEO / 调研 worker 在接通 ``citable_ids`` 时均查。
2. **结构完整性**——代码围栏未闭合（``` 开了没收尾、后文整片被当代码渲染）、或声明了语言却
   空体（标了 ``python`` 却没有任何内容，等于「答应给代码却没给」）。都是「交付不完整」的
   机械信号，最终交付里几乎不会有意为之，故误报率近零。

刻意**不**纳入「残留 TODO / 填空占位」之类：法律垂直会正当地在合同模板留空待填、worker 也会
如实写「该资料待客户提供」，机械判会误伤——轻层的立身之本是近零误报，宁缺毋滥。后续轻层（如
受限的 JSON 可解析）与重层（要跑 / 要重算 / 换眼睛找漏 / 回源对照）在此扩展。

**统一底线**：结构完整性两查对 CEO 与 worker 同样成立，二者收尾都过这道关（worker 回炉经
``run_output_reset`` 干净重写其卡片）；``[n]`` 造引用查仅 CEO 路径开；``#rN`` id 存在闸按
Q5 条件启用（见上）。

→ 见设计: docs/03-AI核心/执行引擎架构设计.md（ReAct 循环 · 交付前核验）
"""

from __future__ import annotations

from agentcore.runtime.citations import invalid_ledger_ref_ids, out_of_range_markers


def finish_guard(
    content: str,
    *,
    citation_count: int,
    check_citations: bool = True,
    citable_ids: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """模型宣布 done 时的轻层守卫：返回「待修正项」列表，空列表 = 放行交付。

    每条都是一句锚定具体事实的修正指令（镜像 ``loop_controller`` 的注入风格——锚到可观测
    的实事而非空泛的「再想想」），由 react_loop 经 :func:`format_guard_steer` 拼成系统
    提示注入、回炉一轮。纯函数、不经 LLM、不靠 CEO 自觉，可独立单测。

    这是**所有 react_loop 收尾共过的统一底线**——CEO captain 与 worker 都在 done 点过此关。
    现查两类，二者的适用面不同：

    1. **造引用**：
       - ``[n]``（仅 ``check_citations``）：越界角标 → 编造引用。
       - ``#rN``（``citable_ids`` 非 None 且正文出现标记）：id ∉ 可引用台账 → 回炉项。
    2. **结构完整性**（始终查）：:func:`_code_fence_reworks`。
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
    bad_refs = invalid_ledger_ref_ids(content, citable_ids)
    if bad_refs:
        marks = "、".join(bad_refs)
        reworks.append(
            f"正文用了 {marks} 这些台账引用来源，但它们不在本回合已登记且可引用的来源台账中"
            "（伪造、越界或弱源不可引用）。请改成提示中「已登记来源」列出的 #rN，"
            "或删除这些引用标记；没有依据就直接去掉这处引用。"
        )
    reworks.extend(_code_fence_reworks(content))
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
