"""辩手发言格式合规度量（两阶段成稿契约）.

背景：辩论室前端 ``parseSpeechArguments`` 按 markdown ``### `` 标题启发式切「论点大纲」；
旧契约把 ReAct 收工 stop 当发言 → 混入过程句。现契约为两阶段——检索产证据笔记、干净成稿
产出发言；``NO_PREAMBLE_RULE`` + ``ARGUMENT_SKELETON_RULE`` 进成稿 ``draft_system``。

本模块把「成稿纪律是否被模型遵守」变成可复跑信号：

1. **合成样本**（:data:`SAMPLES`）：正反双方 × 立论/续辩，≥10 条；每条用生产
   ``draft_system`` + ``draft_brief`` 组装成稿 prompt（开发期无真实数据）。
2. **合成证据笔记→成稿**（:data:`NOTES_DRAFT_SAMPLES`）：显式注入合成笔记，度量
   「有笔记素材时」的成稿形态（注释声明样本为合成）。
3. **直连** ``provider.complete``（不跑 ReAct、不带工具）——只量格式合规，不量取证质量。
4. **合规检查**（:func:`check_speech_format`）：无前言（首行即 ``###``）/ 无总标题 /
   无加粗行伪标题 / 标题 ≤30 字符。

真跑需平台 / ``EVAL_DEEPSEEK_API_KEY``（与 ``debate_converge`` 同凭据解析）；单测注入脚本化
假 provider 零成本验证检查器与样本集结构。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from agentcore.evals.types import EvalConfigError
from agentcore.llm.provider.protocol import LLMMessage, LLMProvider, LLMRequest
from agentcore.runtime.debate.prompt import (
    draft_system,
    opening_draft_brief,
    round_draft_brief,
)
from agentcore.runtime.debate.speech_pipeline import build_draft_user
from agentcore.runtime.debate.types import (
    DebateConfig,
    DebateForm,
    DebateSide,
    JudgeVerdict,
    RoundPolicy,
    RoundResult,
    SideTurn,
)

# 合规：产出端 prompt 纪律更严（≤16）；度量放宽到 30（与展示无关——title 已完整入库）
_TITLE_MAX = 30

# 「X方立论 / 开场立论」类总标题（UI 已渲染方名与阶段，发言里再写会多切一块空壳）
_OVERALL_TITLE = re.compile(
    r"^#{1,3}\s*.{0,12}(?:正方|反方|我方|本方).{0,8}(?:立论|开场|陈词)|"
    r"^#{1,3}\s*(?:开场立论|立论开场|开场陈词)",
    re.MULTILINE,
)

# 加粗行冒充章节标题：单独一行的 **...**（可带前后空白）
_BOLD_PSEUDO_HEADER = re.compile(r"(?m)^\s*\*\*[^*\n]{1,40}\*\*\s*$")


@dataclass(frozen=True)
class SpeechFormatSample:
    """一条辩手发言格式度量样本（成稿生产形态：draft_system + draft_brief）。"""

    id: str
    side_key: str  # pro | con
    beat: str  # opening | continue
    motion: str
    focus: str
    stance_pro: str = "支持做 X"
    stance_con: str = "反对做 X"
    # 续辩时对手上轮发言（opening 忽略）
    opponent_content: str = "对方认为应当谨慎推进，风险尚未摸清。"
    # 可选合成证据笔记（开发期无真实数据；空则成稿 user 用占位「无补充笔记」）
    evidence_notes: str = ""

    def config(self) -> DebateConfig:
        return DebateConfig(
            motion=self.motion,
            form=DebateForm.DEBATE,
            sides=[
                DebateSide(key="pro", name="正方", stance=self.stance_pro),
                DebateSide(key="con", name="反方", stance=self.stance_con),
            ],
            policy=RoundPolicy(thorough=True, max_rounds=5),
        )

    def side(self) -> DebateSide:
        cfg = self.config()
        return cfg.sides[0] if self.side_key == "pro" else cfg.sides[1]

    def last_round(self) -> RoundResult:
        """续辩用的上一轮占位（双方各一句，保证 round_draft_brief 有对手块）。"""
        cfg = self.config()
        pro, con = cfg.sides
        if self.side_key == "pro":
            mine, opp = "正方上轮已论证成本可控。", self.opponent_content
            turns = [
                SideTurn("pro", pro.name, "r1_pro", mine, ok=True),
                SideTurn("con", con.name, "r1_con", opp, ok=True),
            ]
        else:
            mine, opp = "反方上轮已论证风险缺兜底。", self.opponent_content
            turns = [
                SideTurn("pro", pro.name, "r1_pro", opp, ok=True),
                SideTurn("con", con.name, "r1_con", mine, ok=True),
            ]
        return RoundResult(
            1,
            "上一轮焦点",
            turns,
            JudgeVerdict(real_clash=True, new_arguments=True, converged=False),
        )

    def build_messages(self) -> tuple[str, str]:
        """返回 (system, user) —— 生产成稿形态 draft_system + draft_user(brief, notes)。"""
        cfg = self.config()
        side = self.side()
        system = draft_system(
            cfg, side, beat="opening" if self.beat == "opening" else "continue"
        )
        if self.beat == "opening":
            brief = opening_draft_brief(cfg, side, focus=self.focus)
        elif self.beat == "continue":
            brief = round_draft_brief(cfg, side, 2, self.focus, self.last_round())
        else:
            raise EvalConfigError(f"未知 beat={self.beat!r}（仅 opening/continue）")
        user = build_draft_user(brief, self.evidence_notes)
        return system, user


# --- 样本集：正反 × 立论/续辩，≥10（成稿形态，无真实笔记） --------------------

SAMPLES: tuple[SpeechFormatSample, ...] = (
    SpeechFormatSample(
        id="pro_open_remote",
        side_key="pro",
        beat="opening",
        motion="公司该不该全面转向远程办公",
        focus="远程办公对协作效率的净影响",
        stance_pro="支持全面远程办公",
        stance_con="反对全面远程办公",
    ),
    SpeechFormatSample(
        id="con_open_remote",
        side_key="con",
        beat="opening",
        motion="公司该不该全面转向远程办公",
        focus="远程办公对协作效率的净影响",
        stance_pro="支持全面远程办公",
        stance_con="反对全面远程办公",
    ),
    SpeechFormatSample(
        id="pro_cont_remote",
        side_key="pro",
        beat="continue",
        motion="公司该不该全面转向远程办公",
        focus="远程对人才池与留存的影响",
        stance_pro="支持全面远程办公",
        stance_con="反对全面远程办公",
        opponent_content="反方认为远程削弱文化与辅导带宽，新人成长变慢。",
    ),
    SpeechFormatSample(
        id="con_cont_remote",
        side_key="con",
        beat="continue",
        motion="公司该不该全面转向远程办公",
        focus="远程对人才池与留存的影响",
        stance_pro="支持全面远程办公",
        stance_con="反对全面远程办公",
        opponent_content="正方认为远程扩大招聘半径、降低通勤损耗。",
    ),
    SpeechFormatSample(
        id="pro_open_dark",
        side_key="pro",
        beat="opening",
        motion="有限工期下产品先做深色模式还是无障碍支持",
        focus="有限工期下先做哪个",
        stance_pro="主张先做深色模式",
        stance_con="主张先做无障碍支持",
    ),
    SpeechFormatSample(
        id="con_open_dark",
        side_key="con",
        beat="opening",
        motion="有限工期下产品先做深色模式还是无障碍支持",
        focus="有限工期下先做哪个",
        stance_pro="主张先做深色模式",
        stance_con="主张先做无障碍支持",
    ),
    SpeechFormatSample(
        id="pro_cont_dark",
        side_key="pro",
        beat="continue",
        motion="有限工期下产品先做深色模式还是无障碍支持",
        focus="合规风险与用户覆盖",
        stance_pro="主张先做深色模式",
        stance_con="主张先做无障碍支持",
        opponent_content="反方指出无障碍关乎合规与基本可达，不可后置。",
    ),
    SpeechFormatSample(
        id="con_cont_dark",
        side_key="con",
        beat="continue",
        motion="有限工期下产品先做深色模式还是无障碍支持",
        focus="合规风险与用户覆盖",
        stance_pro="主张先做深色模式",
        stance_con="主张先做无障碍支持",
        opponent_content="正方认为深色模式覆盖夜间用户、品牌感知立竿见影。",
    ),
    SpeechFormatSample(
        id="pro_open_migrate",
        side_key="pro",
        beat="opening",
        motion="该不该把核心交易库从单体迁到分布式",
        focus="迁移窗口期的可靠性风险",
        stance_pro="支持分阶段迁移",
        stance_con="反对近期迁移、主张先优化单体",
    ),
    SpeechFormatSample(
        id="con_open_migrate",
        side_key="con",
        beat="opening",
        motion="该不该把核心交易库从单体迁到分布式",
        focus="迁移窗口期的可靠性风险",
        stance_pro="支持分阶段迁移",
        stance_con="反对近期迁移、主张先优化单体",
    ),
    SpeechFormatSample(
        id="pro_cont_migrate",
        side_key="pro",
        beat="continue",
        motion="该不该把核心交易库从单体迁到分布式",
        focus="成本与团队带宽",
        stance_pro="支持分阶段迁移",
        stance_con="反对近期迁移、主张先优化单体",
        opponent_content="反方认为双写与回滚演练会吃掉两季度带宽。",
    ),
    SpeechFormatSample(
        id="con_cont_migrate",
        side_key="con",
        beat="continue",
        motion="该不该把核心交易库从单体迁到分布式",
        focus="成本与团队带宽",
        stance_pro="支持分阶段迁移",
        stance_con="反对近期迁移、主张先优化单体",
        opponent_content="正方认为可按只读副本先行、主路径后切，风险可控。",
    ),
)


# --- 合成证据笔记→成稿（开发期无真实数据；下列笔记均为合成样本） --------------
#
# 声明：以下 evidence_notes 为开发期合成，非真实辩论/检索产物，仅用于度量
# 「有笔记素材时」成稿是否仍遵守骨架纪律。

_SYNTH_NOTES_COST = (
    "- 首年可降本约 18%【待核实·推断】（合成：内部测算口径）\n"
    "- 迁移期双写窗口可设熔断【待核实·推断】\n"
    "- 对手攻击点：辅导带宽与新人成长"
)

_SYNTH_NOTES_COMPLIANCE = (
    "- 无障碍关乎合规可达【待核实·推断】\n"
    "- 深色模式夜间覆盖与品牌感知【待核实·推断】\n"
    "- 有限工期下须二选一优先级"
)

NOTES_DRAFT_SAMPLES: tuple[SpeechFormatSample, ...] = (
    SpeechFormatSample(
        id="pro_open_notes_cost",
        side_key="pro",
        beat="opening",
        motion="公司该不该全面转向远程办公",
        focus="远程办公对协作效率的净影响",
        stance_pro="支持全面远程办公",
        stance_con="反对全面远程办公",
        evidence_notes=_SYNTH_NOTES_COST,
    ),
    SpeechFormatSample(
        id="con_cont_notes_cost",
        side_key="con",
        beat="continue",
        motion="公司该不该全面转向远程办公",
        focus="远程对人才池与留存的影响",
        stance_pro="支持全面远程办公",
        stance_con="反对全面远程办公",
        opponent_content="正方认为远程扩大招聘半径、降低通勤损耗。",
        evidence_notes=_SYNTH_NOTES_COST,
    ),
    SpeechFormatSample(
        id="pro_open_notes_a11y",
        side_key="pro",
        beat="opening",
        motion="有限工期下产品先做深色模式还是无障碍支持",
        focus="有限工期下先做哪个",
        stance_pro="主张先做深色模式",
        stance_con="主张先做无障碍支持",
        evidence_notes=_SYNTH_NOTES_COMPLIANCE,
    ),
    SpeechFormatSample(
        id="con_cont_notes_a11y",
        side_key="con",
        beat="continue",
        motion="有限工期下产品先做深色模式还是无障碍支持",
        focus="合规风险与用户覆盖",
        stance_pro="主张先做深色模式",
        stance_con="主张先做无障碍支持",
        opponent_content="正方认为深色模式覆盖夜间用户、品牌感知立竿见影。",
        evidence_notes=_SYNTH_NOTES_COMPLIANCE,
    ),
)


@dataclass(frozen=True)
class FormatCheckResult:
    """单条发言的合规检查结果。"""

    ok: bool
    failures: tuple[str, ...] = ()
    titles: tuple[str, ...] = ()


def check_speech_format(text: str) -> FormatCheckResult:
    """确定性合规检查（无 LLM）：无前言 / 无总标题 / 无加粗伪标题 / 标题 ≤30。"""
    raw = (text or "").strip()
    failures: list[str] = []
    if not raw:
        return FormatCheckResult(ok=False, failures=("empty",))

    first_line = raw.split("\n", 1)[0].strip()
    if not first_line.startswith("### "):
        failures.append("preamble_or_not_h3_first")

    if _OVERALL_TITLE.search(raw):
        failures.append("overall_title")

    if _BOLD_PSEUDO_HEADER.search(raw):
        failures.append("bold_pseudo_header")

    titles: list[str] = []
    for m in re.finditer(r"(?m)^###\s+(.+)$", raw):
        title = m.group(1).strip()
        titles.append(title)
        if len(title) > _TITLE_MAX:
            failures.append(f"title_too_long:{len(title)}")

    # 有 ### 但首行不是 ### 时仍可能切出标题；首行合规时至少应有 1 个标题
    if first_line.startswith("### ") and not titles:
        failures.append("no_h3_titles")

    return FormatCheckResult(
        ok=not failures, failures=tuple(failures), titles=tuple(titles)
    )


@dataclass
class SampleJudgement:
    id: str
    side_key: str
    beat: str
    ok: bool
    failures: tuple[str, ...]
    titles: tuple[str, ...]
    content: str
    content_preview: str = ""

    def __post_init__(self) -> None:
        preview = (self.content or "").strip().replace("\n", "\\n")
        object.__setattr__(self, "content_preview", preview[:160])


@dataclass
class SpeechFormatMetrics:
    per: list[SampleJudgement] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.per)

    @property
    def n_ok(self) -> int:
        return sum(1 for x in self.per if x.ok)

    @property
    def compliance_rate(self) -> float:
        return self.n_ok / self.n if self.n else 0.0

    @property
    def failures(self) -> list[SampleJudgement]:
        return [x for x in self.per if not x.ok]


def lint_samples(samples: Sequence[SpeechFormatSample] = SAMPLES) -> None:
    """零 LLM：校验样本集结构（≥10、正反×立论/续辩覆盖、id 唯一、成稿 prompt 可组装）。"""
    if len(samples) < 10:
        raise EvalConfigError(f"辩手格式样本不足 10 条（got {len(samples)}）")
    ids = [s.id for s in samples]
    if len(ids) != len(set(ids)):
        raise EvalConfigError("辩手格式样本 id 不唯一")
    sides = {s.side_key for s in samples}
    beats = {s.beat for s in samples}
    if sides != {"pro", "con"}:
        raise EvalConfigError(f"样本须覆盖正反双方（got {sides}）")
    if not {"opening", "continue"} <= beats:
        raise EvalConfigError(f"样本须覆盖立论与续辩（got {beats}）")
    for s in samples:
        system, user = s.build_messages()
        if "禁止任何寒暄" not in system and "禁止前言" not in system:
            raise EvalConfigError(f"{s.id}: draft_system 缺禁止前言纪律")
        if "论点骨架" not in system:
            raise EvalConfigError(f"{s.id}: draft_system 缺论点骨架纪律")
        if "发言任务" not in user:
            raise EvalConfigError(f"{s.id}: draft user 缺发言任务块")
        if "证据笔记" not in user:
            raise EvalConfigError(f"{s.id}: draft user 缺证据笔记块")


def lint_notes_draft_samples(
    samples: Sequence[SpeechFormatSample] = NOTES_DRAFT_SAMPLES,
) -> None:
    """零 LLM：校验合成笔记→成稿样本（开发期合成，须带非空 evidence_notes）。"""
    if len(samples) < 2:
        raise EvalConfigError(f"合成笔记成稿样本不足 2 条（got {len(samples)}）")
    ids = [s.id for s in samples]
    if len(ids) != len(set(ids)):
        raise EvalConfigError("合成笔记成稿样本 id 不唯一")
    for s in samples:
        if not (s.evidence_notes or "").strip():
            raise EvalConfigError(f"{s.id}: 合成笔记样本须带非空 evidence_notes")
        system, user = s.build_messages()
        if "论点骨架" not in system:
            raise EvalConfigError(f"{s.id}: draft_system 缺论点骨架纪律")
        if s.evidence_notes.strip() not in user:
            raise EvalConfigError(f"{s.id}: 合成笔记未进入 draft user")


async def run_debate_speech_format(
    provider: LLMProvider,
    model: str,
    samples: Sequence[SpeechFormatSample] = SAMPLES,
) -> SpeechFormatMetrics:
    """对每个样本直连 ``provider.complete``（无工具），检查发言格式合规。"""
    if not samples:
        raise EvalConfigError("辩手格式样本集为空")
    per: list[SampleJudgement] = []
    for s in samples:
        system, user = s.build_messages()
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user),
            ],
            model=model,
            temperature=0.4,
            stream=False,
            tools=None,
            scenario="eval.debate_speech_format",
        )
        response = await provider.complete(request)
        content = (response.content or "").strip()
        checked = check_speech_format(content)
        per.append(
            SampleJudgement(
                id=s.id,
                side_key=s.side_key,
                beat=s.beat,
                ok=checked.ok,
                failures=checked.failures,
                titles=checked.titles,
                content=content,
            )
        )
    return SpeechFormatMetrics(per=per)


def _debate_provider_and_model(mode: str = "quality") -> tuple[LLMProvider, str]:
    """构造接真实 LLM 的 (provider, model) —— 与辩手/主持人同档偏好。

    模型优先 ``EVAL_DEBATE_MODEL``，其次 ``settings.platform_model``（``.env`` 实跑），
    再回落 eval quality 档的 ``agent`` profile（``TurnProfiles.model_for``）。
    凭据复用 eval 专用解析（无 ``EVAL_DEEPSEEK_API_KEY`` 时回落平台 key）。
    """
    import os

    from agentcore.config import settings
    from agentcore.evals.eval_modes import resolve_profile_set
    from agentcore.evals.harness import _EVAL_CEILING, _eval_credentials
    from agentcore.llm.factory import build_provider

    provider = build_provider(_eval_credentials())
    model = os.environ.get("EVAL_DEBATE_MODEL", "").strip()
    if not model:
        model = (settings.platform_model or "").strip()
    if not model:
        profiles = resolve_profile_set(mode, custom_modes={}, ceiling=_EVAL_CEILING)
        model = profiles.model_for("agent")
    return provider, model


def debate_speech_format_to_dict(m: SpeechFormatMetrics) -> dict:
    return {
        "n": m.n,
        "n_ok": m.n_ok,
        "compliance_rate": round(m.compliance_rate, 4),
        "per_sample": [
            {
                "id": x.id,
                "side_key": x.side_key,
                "beat": x.beat,
                "ok": x.ok,
                "failures": list(x.failures),
                "titles": list(x.titles),
                "content_preview": x.content_preview,
                "content": x.content,
            }
            for x in m.per
        ],
    }


def format_debate_speech_format_report(m: SpeechFormatMetrics) -> str:
    lines: list[str] = ["=" * 68, "AgentCore 辩手发言格式合规（两阶段成稿纪律）", "=" * 68]
    lines.append(f"  样本 {m.n}    合规 {m.n_ok}    合规率 {m.compliance_rate * 100:.0f}%")
    lines.append("-" * 68)
    fails = m.failures
    if fails:
        lines.append(f"  失败 {len(fails)} 条:")
        for x in fails:
            lines.append(f"    [{x.id}] {x.side_key}/{x.beat}  failures={list(x.failures)}")
            lines.append(f"        preview: {x.content_preview[:120]}")
    else:
        lines.append("  全部合规：首行 ###、无总标题、无加粗伪标题、标题<=30。")
    lines.append("=" * 68)
    return "\n".join(lines)
