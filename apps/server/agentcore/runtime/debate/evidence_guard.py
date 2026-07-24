"""成稿【已核实】证据标签守卫（纯函数，零 I/O）。

证据台账闸：成稿中每个 ``【已核实·…】`` 必须含**本方笔记引用集**内的 ``#eN``
（结辩无检索 = 本方历轮已引用并集）；否则回炉一次，二次违规剥离降级为【待核实·推断】（O2）。

仍是机械存在性判定（零误报纪律不变）——基准从「id ∈ 场级台账」收紧为
「id ∈ 本方笔记引用集」。结辩白名单闸与 A2 出处 n-gram 软校验已退役。
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence

# 完整 / 残缺【已核实】标签均由 extract_verified_tags 统一抽取。
_VERIFIED_TAG_PREFIX = "【已核实·"
_PENDING_INFER = "【待核实·推断】"
# 标签 note 内的台账 id（允许纯 ``#e3`` 或出处短语+#e3 双写）。
_LEDGER_ID_RE = re.compile(r"#e(\d+)\b")


def extract_verified_tags(text: str) -> set[str]:
    """从正文抽取【已核实·出处】标签（含未闭合残缺片段）。"""
    raw = text or ""
    out: set[str] = set()
    prefix_len = len(_VERIFIED_TAG_PREFIX)
    for m in re.finditer(re.escape(_VERIFIED_TAG_PREFIX), raw):
        start = m.start()
        rest = raw[start + prefix_len :]
        close = rest.find("】")
        if close == -1:
            # 未闭合：截到行尾 / 下一个【 / 文末
            end_rel = len(rest)
            for sep in ("\n", "【"):
                i = rest.find(sep)
                if i != -1:
                    end_rel = min(end_rel, i)
            frag = raw[start : start + prefix_len + end_rel]
            if frag:
                out.add(frag)
        else:
            out.add(raw[start : start + prefix_len + close + 1])
    return out


def ledger_id_in_tag(tag: str) -> str | None:
    """从【已核实·…】标签抽出 ``#eN``；无则 None（含残缺未闭合）。"""
    if not tag.startswith(_VERIFIED_TAG_PREFIX):
        return None
    if not tag.endswith("】"):
        return None
    note = tag[len(_VERIFIED_TAG_PREFIX) : -1]
    m = _LEDGER_ID_RE.search(note)
    if not m:
        return None
    return f"#e{m.group(1)}"


def invalid_verified_tags(
    speech: str, known_ids: Collection[str]
) -> list[str]:
    """成稿中 id ∉ 允许集、或根本无 id 的【已核实】标签（稳定排序）。

    残缺未闭合标签一律视为违规。``known_ids`` = 本方笔记引用集（或结辩历轮并集）。
    """
    known = set(known_ids)
    out: list[str] = []
    for tag in sorted(extract_verified_tags(speech)):
        eid = ledger_id_in_tag(tag)
        if eid is None or eid not in known:
            out.append(tag)
    return out


def demote_verified_tags(text: str, tags: Sequence[str]) -> str:
    """把违规【已核实·…】（含残缺）替换为【待核实·推断】；按长度降序替换防前缀互吞。"""
    result = text or ""
    for tag in sorted((t for t in tags if t), key=len, reverse=True):
        result = result.replace(tag, _PENDING_INFER)
    return result


def format_evidence_ledger_steer(invalid_tags: Sequence[str]) -> str:
    """台账 id 闸的回炉提示（``[系统提示]`` 口径，镜像 verify.format_guard_steer）。"""
    if not invalid_tags:
        return ""
    listed = "、".join(invalid_tags)
    return (
        "[系统提示] 交付前核验未通过（系统自动核验，非用户反馈），发现以下问题：\n"
        f"- 以下【已核实】标签未引用本方证据笔记中出现过的台账 id，或引用了未绑定的 id：{listed}。"
        "【已核实】只能写成【已核实·#eN】（N 须已出现在本方本轮证据笔记；结辩则须为本方历轮已用过的 id）；"
        "拿不出已绑定 id 的主张改标【待核实·推断】或删除该主张。\n"
        "请直接修正正文后再给出最终发言；不要为此道谢、复述或寒暄，直接改。"
    )
