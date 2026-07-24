"""红队三拍 / 圆桌点名串行 —— 由既有 RoundRunner + 材料注入组合（无新执行原语）。

→ 见提案: docs/06-规划/红队与圆桌形态重设计提案.md §3.2–3.3、O3–O8
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from agentcore.core.logging import get_logger
from agentcore.runtime.debate.findings import (
    apply_merge_plan,
    apply_rebuttal_statuses,
    findings_from_attack_turns,
    format_findings_block,
    mark_answered,
    mark_unanswered,
)
from agentcore.runtime.debate.form_profile import FormProfile
from agentcore.runtime.debate.moderator_common import CompleteJson, _as_str, _as_str_list
from agentcore.runtime.debate.types import (
    DebateConfig,
    DebateSide,
    Finding,
    RoundResult,
    RoundRunner,
    SideTurn,
    ThreadTurn,
    UserInterjection,
)

logger = get_logger(__name__)

_MERGE_SYSTEM = (
    "你是红队审查主持人。现在合并多路红队挖出的 finding：宁少合并勿误合并——"
    "仅当两条明显指向同一风险部位且主张同义时才合并；不确定则保留两条。"
    "严格只输出要求的 JSON。"
)

_NOMINATE_SYSTEM = (
    "你是多方圆桌主持人。为本子题点名 2–3 位最相关视角依次发言；"
    "须兼顾「每人每场至少被点一次」的保底（未点过的优先）。严格只输出要求的 JSON。"
)


async def merge_findings(
    complete_json: CompleteJson,
    config: DebateConfig,
    focus: str,
    seeds: list[Finding],
) -> list[Finding]:
    """主持人去重合并（O5）。坏 JSON → 原样 seeds。"""
    if len(seeds) <= 1:
        return seeds
    lines = format_findings_block(seeds, include_claim=True)
    ids = ", ".join(f.id for f in seeds)
    user = (
        f"命题：{config.motion}\n本轮焦点：{focus}\n\n本轮 finding 种子：\n{lines}\n\n"
        "请输出合并计划：keep=保留的 id 列表；merges=合并项（into 保留方，from 被吞并 id）。"
        "宁少合并。只输出 JSON：\n"
        f'{{"keep": [{ids!r} 的子集], "merges": [{{"into": "id", "from": ["id"]}}]}}'
    )
    # 修正示例里的 ids 展示
    user = (
        f"命题：{config.motion}\n本轮焦点：{focus}\n\n本轮 finding 种子：\n{lines}\n\n"
        f"可选 id：{ids}\n"
        "请输出合并计划：keep=保留的 id 列表；merges=合并项（into 保留方，from 被吞并 id）。"
        "宁少合并勿误合并。只输出 JSON：\n"
        '{"keep": ["..."], "merges": [{"into": "...", "from": ["..."]}]}'
    )
    data = await complete_json(_MERGE_SYSTEM, user, "merge_findings")
    if not data:
        return seeds
    return apply_merge_plan(seeds, data)


async def nominate_speakers(
    complete_json: CompleteJson,
    config: DebateConfig,
    focus: str,
    *,
    spoken_keys: set[str],
    n: int = 3,
) -> list[str]:
    """点名 2–3 位（O4：LLM 选人 + 未点过者保底优先）。坏 JSON → 轮转保底。"""
    sides = list(config.sides)
    keys = [s.key for s in sides]
    if not keys:
        return []
    never = [k for k in keys if k not in spoken_keys]
    hint = (
        f"尚未被点名（须优先）：{', '.join(never)}\n" if never else "本场各方均已被点过至少一次。\n"
    )
    user = (
        f"命题：{config.motion}\n本子题：{focus}\n参与方：{', '.join(f'{s.name}[{s.key}]' for s in sides)}\n"
        f"{hint}"
        f"请点名 {min(n, len(keys))} 位按发言顺序的 side_key 列表（2–3 人）。"
        '只输出 JSON：{"speakers": ["key", ...]}'
    )
    data = await complete_json(_NOMINATE_SYSTEM, user, "nominate")
    raw = _as_str_list(data.get("speakers")) if data else []
    ordered = [k for k in raw if k in keys]
    # 保底：未点过者插到前面
    for k in never:
        if k not in ordered:
            ordered.insert(0, k)
    if not ordered:
        # 机械轮转
        start = len(spoken_keys) % len(keys)
        ordered = keys[start:] + keys[:start]
    return ordered[: max(2, min(n, len(keys)))]


def split_interjections_for_red_team(
    interjections: Sequence[UserInterjection],
    subject_key: str,
) -> tuple[list[UserInterjection], list[UserInterjection]]:
    """O8：定向方案方的追问进回应拍，其余进攻击波。"""
    to_defense: list[UserInterjection] = []
    to_attack: list[UserInterjection] = []
    for i in interjections:
        if i.target_key and i.target_key == subject_key:
            to_defense.append(i)
        else:
            to_attack.append(i)
    return to_attack, to_defense


async def run_red_team_round(
    *,
    complete_json: CompleteJson,
    config: DebateConfig,
    profile: FormProfile,
    run_round: RoundRunner,
    round_no: int,
    focus: str,
    history: list[RoundResult],
    interjections: Sequence[UserInterjection],
    prior_findings: Sequence[Finding] = (),
) -> tuple[list[SideTurn], list[Finding]]:
    """一轮红队：攻 → 合并 → 应 →（thorough）复攻。返回 (turns beat 化, findings)。"""
    subject = config.subject_side
    if subject is None:
        # 无方案方：退化为全体并行（不应在合法配置出现）
        logger.warning("debate.red_team.no_subject")
        turns = list(
            await run_round(
                round_no=round_no,
                focus=focus,
                sides=config.sides,
                history=history,
                interjections=interjections,
                beat="statement",
            )
        )
        return turns, []

    red_sides = [s for s in config.sides if not s.is_subject]
    attack_ask, defense_ask = split_interjections_for_red_team(interjections, subject.key)

    # ① 攻击波：全体红队并行；escalated 优先注入 materials
    prior_esc = [f for f in prior_findings if f.status.value == "escalated"]
    esc_block = (
        "【上轮 escalate 优先位】\n" + format_findings_block(prior_esc) if prior_esc else ""
    )
    attack_raw = list(
        await run_round(
            round_no=round_no,
            focus=focus,
            sides=red_sides,
            history=history,
            interjections=attack_ask,
            beat="attack",
            materials=esc_block,
        )
    )
    attack_turns = [replace(t, beat="attack") for t in attack_raw]

    seeds = findings_from_attack_turns(attack_turns, round_no=round_no)
    findings = await merge_findings(complete_json, config, focus, seeds)

    # ② 回应拍：方案方单独；O7 失败重试一次
    findings_mat = (
        "【本轮 finding 清单·请逐条处置：接受/缓解/反驳/挂起，每条给理由与证据】\n"
        + format_findings_block(findings)
    )
    defense_turn = await _run_subject_defense(
        run_round,
        subject=subject,
        round_no=round_no,
        focus=focus,
        history=history,
        interjections=defense_ask,
        materials=findings_mat,
    )
    turns: list[SideTurn] = list(attack_turns)
    if defense_turn is None or not defense_turn.ok:
        findings = mark_unanswered(findings)
        if defense_turn is not None:
            turns.append(replace(defense_turn, beat="defense", absent=True, ok=False))
        else:
            turns.append(
                SideTurn(
                    subject.key,
                    subject.name,
                    f"r{round_no}_{subject.key}_defense",
                    "",
                    ok=False,
                    absent=True,
                    beat="defense",
                )
            )
        return turns, findings

    turns.append(replace(defense_turn, beat="defense"))
    findings = mark_answered(findings, response_run_id=defense_turn.run_id)

    # ③ 复攻拍（O3：快速档跳过）
    if not profile.has_rebuttal:
        return turns, findings

    rebut_mat = (
        "【方案方处置·请逐条复核：closed/escalated/deadlocked；禁止重复原刺；"
        "被合并方可申诉拆分】\n"
        + format_findings_block(findings)
    )
    rebut_raw = list(
        await run_round(
            round_no=round_no,
            focus=focus,
            sides=red_sides,
            history=history,
            interjections=(),
            beat="rebuttal",
            materials=rebut_mat,
        )
    )
    rebut_turns = [replace(t, beat="rebuttal") for t in rebut_raw]
    turns.extend(rebut_turns)
    # 启发式：成功复攻 → escalated；失败保持 answered（裁判可再改）
    status_map: dict[str, str] = {}
    run_ids = {t.side_key: t.run_id for t in rebut_turns if t.ok}
    for f in findings:
        if f.attacker_key in run_ids:
            status_map[f.id] = "escalated"
        else:
            status_map[f.id] = "closed"
    findings = apply_rebuttal_statuses(findings, status_map, rebuttal_run_ids=run_ids)
    return turns, findings


async def _run_subject_defense(
    run_round: RoundRunner,
    *,
    subject: DebateSide,
    round_no: int,
    focus: str,
    history: list[RoundResult],
    interjections: Sequence[UserInterjection],
    materials: str,
) -> SideTurn | None:
    """回应拍：失败重试一次（O7）。"""
    for _attempt in range(2):
        raw = list(
            await run_round(
                round_no=round_no,
                focus=focus,
                sides=[subject],
                history=history,
                interjections=interjections,
                beat="defense",
                materials=materials,
            )
        )
        if raw and raw[0].ok:
            return raw[0]
        last = raw[0] if raw else None
    return last


async def run_roundtable_round(
    *,
    complete_json: CompleteJson,
    config: DebateConfig,
    run_round: RoundRunner,
    round_no: int,
    focus: str,
    history: list[RoundResult],
    interjections: Sequence[UserInterjection],
    spoken_keys: set[str],
) -> tuple[list[SideTurn], list[ThreadTurn], set[str]]:
    """一轮圆桌：点名串行 + 可选 crux 追问。O8：追问交主持人作线程内点名消费。"""
    speakers = await nominate_speakers(
        complete_json, config, focus, spoken_keys=spoken_keys
    )
    # O8：若有追问，把 target 插进点名（或追加）
    for inj in interjections:
        if (
            inj.target_key
            and inj.target_key in {s.key for s in config.sides}
            and inj.target_key not in speakers
        ):
            speakers.append(inj.target_key)

    side_by_key = {s.key: s for s in config.sides}
    thread: list[ThreadTurn] = []
    turns: list[SideTurn] = []
    thread_so_far = ""

    for key in speakers:
        side = side_by_key.get(key)
        if side is None:
            continue
        reply_to = thread[-1].speaker if thread else ""
        mat = (
            "【本线程已有发言·请先回应已说的、再补自己的】\n" + thread_so_far
            if thread_so_far
            else "【本子题开题·请提出你的核心主张】"
        )
        if interjections and key in {i.target_key for i in interjections if i.target_key}:
            asks = [i.ask for i in interjections if i.target_key == key]
            mat += "\n【主持人转达的用户追问】\n" + "\n".join(f"- {a}" for a in asks)

        raw = list(
            await run_round(
                round_no=round_no,
                focus=focus,
                sides=[side],
                history=history,
                interjections=(),
                beat="thread",
                materials=mat,
            )
        )
        if not raw:
            # 失败跳过（提案：线程降级不阻塞）
            continue
        t = replace(raw[0], beat="thread")
        if not t.ok:
            logger.info("debate.roundtable.speaker_skipped", side_key=key, round_no=round_no)
            continue
        turns.append(t)
        tt = ThreadTurn(
            speaker=key,
            run_id=t.run_id,
            reply_to=reply_to,
            ok=True,
            content=t.content,
            beat="thread",
        )
        thread.append(tt)
        spoken_keys.add(key)
        thread_so_far += f"\n### {side.name}\n{t.content}\n"

    # crux 追问：线程 ≥2 且有实质内容时追一次（坏 JSON / 无分歧 → 跳过）
    if len(thread) >= 2:
        crux_pair = await _maybe_crux(
            complete_json, config, focus, thread, side_by_key, run_round, round_no, history
        )
        if crux_pair:
            turns.extend(crux_pair[0])
            thread.extend(crux_pair[1])

    return turns, thread, spoken_keys


async def _maybe_crux(
    complete_json: CompleteJson,
    config: DebateConfig,
    focus: str,
    thread: list[ThreadTurn],
    side_by_key: dict[str, DebateSide],
    run_round: RoundRunner,
    round_no: int,
    history: list[RoundResult],
) -> tuple[list[SideTurn], list[ThreadTurn]] | None:
    """主持人判是否有实质分歧；有则点两方短答一次。"""
    body = "\n".join(
        f"- {t.speaker}: {(t.content or '')[:400]}" for t in thread if t.ok
    )
    user = (
        f"子题：{focus}\n线程摘要：\n{body}\n\n"
        "若存在实质分歧，输出双方 side_key 与一句追问（事实之争还是价值之争？）；"
        "若无明显分歧，diverged=false。"
        '只输出 JSON：{"diverged": true, "speakers": ["a","b"], "question": "..."}'
    )
    data = await complete_json(
        "你是圆桌主持人，只在实质分歧时追问一次 crux。严格 JSON。",
        user,
        "crux",
    )
    if not data or not data.get("diverged"):
        return None
    pair = [k for k in _as_str_list(data.get("speakers")) if k in side_by_key][:2]
    question = _as_str(data.get("question")) or "你们的分歧是事实之争还是价值之争？"
    if len(pair) < 2:
        return None
    turns: list[SideTurn] = []
    tts: list[ThreadTurn] = []
    for key in pair:
        side = side_by_key[key]
        mat = f"【crux 短答】主持人追问：{question}\n请用 2–4 句正面回答，挖到 crux 即止。"
        raw = list(
            await run_round(
                round_no=round_no,
                focus=focus,
                sides=[side],
                history=history,
                interjections=(),
                beat="crux",
                materials=mat,
            )
        )
        if not raw or not raw[0].ok:
            continue
        t = replace(raw[0], beat="crux")
        turns.append(t)
        tts.append(
            ThreadTurn(
                speaker=key,
                run_id=t.run_id,
                reply_to="moderator",
                ok=True,
                content=t.content,
                beat="crux",
            )
        )
    return (turns, tts) if turns else None


async def frame_subtopics(
    complete_json: CompleteJson,
    config: DebateConfig,
) -> list[str]:
    """圆桌 frame：拆 2–4 个子题轴。坏 JSON → 单题兜底。"""
    user = (
        f"命题：{config.motion}\n参与方：{', '.join(s.name for s in config.sides)}\n\n"
        "请把命题拆成 2–4 个【子题轴】（每条≤20 字短语），用于逐轮铺光谱。"
        '只输出 JSON：{"subtopics": ["...", "..."]}'
    )
    data = await complete_json(
        "你是圆桌主持人，负责拆子题轴。严格 JSON。",
        user,
        "subtopics",
    )
    topics = _as_str_list(data.get("subtopics")) if data else []
    topics = [t for t in topics if t][:4]
    if len(topics) < 2:
        return [config.motion[:30] or "核心争议"]
    return topics
