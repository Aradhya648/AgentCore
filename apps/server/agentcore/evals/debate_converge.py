"""辩论收敛校准（§三：先量化再调裁判是否系统性过保守）.

对应 `辩论编排设计.md §五`（收敛治理）暴露的疑点：一场真实辩论 5 轮全程 `converged=false`、
靠 `max_rounds` 兜底停——裁判 [`_judge_and_summarize`](../runtime/debate/moderator.py) 可能【系统性
过于不愿收敛】。但那是 **n=1** 观察：拿单样本调裁判 prompt 极易过拟合。本模块把「裁判是否过保守」
变成 **可量化、可复跑**的信号，遵循「先量化再调」（dev-process：开发期无真实数据 →
以合成样本为据）。

做法与 `calibration.py`（校准 eval LLMJudge ↔ 人工分）同构，但校准的是**辩论裁判自身的收敛判定**：

1. **合成场景**（:data:`SCENARIOS`）：一组人工编写、带**金标 `expect_converge`** 的单轮辩论态——
   覆盖「该收敛」（论点见顶重复 / 归结为价值之争 / 红队风险挖尽 / 快速单轮）与「该继续」
   （开场首轮 / 冒出实质新论点 / 圆桌新视角 / 红队新风险）两侧。
2. **过真实裁判**（:func:`run_debate_converge`）：对每个场景构 `DebateConfig` + 当前轮发言 + 历史
   长度（定 `round_no`），调**生产合并裁判 `_judge_and_summarize`** 取 `converged`（只读其裁判判定
   部分、弃小结），与金标比。
3. **过保守信号**（:class:`ConvergeMetrics`）：混淆矩阵 + 两侧错误率——**over-conservatism（该收敛却
   判继续）** 是本盘点关心的主信号，premature（该继续却判收敛）是反向错误；另出二分 Cohen's
   kappa（判↔金标一致度，复用 `calibration.cohens_kappa`）。

**关键事实（决定怎么读结果 + 怎么编场景）**：合并裁判 `_judge_and_summarize` 的【收敛判定】看两块
输入——① 当前轮发言；② 前几轮的【论点账本】（收敛校准 §三 H2：`_prior_ledger` 把 `history` 的
focus/summary/clashes 压成紧凑账本喂进裁判，让 `new_arguments` 能判「本轮相比前几轮是否还有跨轮
新论点」）。故本场景集覆盖两类信号：
- **in-round**（`prior_rounds` 留空）：收敛信号落在当前轮发言里（辩手自报「无新论点」/ 分歧已成
  价值僵局 / 快速单轮）——量裁判对当前轮信号的敏感度（≈ H1 过保守假设）。
- **cross-round**（`prior_rounds` 给足账本）：当前轮把账本里的老论点**换措辞重述、且不自报重复**，
  须靠跨轮账本才判得出「无跨轮新论点 → 收敛」——量裁判是否补上了「跨轮重复不可见」这一结构盲区
  （H2，正是真实 trace 5 轮撞满 max_rounds 的形态）。

真跑需 `EVAL_DEEPSEEK_API_KEY`（模型档见 :func:`_debate_provider_and_model`）；单测注入脚本化假
provider 零成本验证度量与场景集结构（见 tests/test_debate_converge.py）。本模块只 import `types` /
`calibration`（纯）+ 轻量的 `runtime.debate`（不拖 pipeline/engine），故不进 `__init__` 静态面。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from agentcore.evals.calibration import cohens_kappa
from agentcore.evals.types import EvalConfigError
from agentcore.llm.provider.protocol import LLMProvider
from agentcore.runtime.debate.moderator import Moderator
from agentcore.runtime.debate.types import (
    STOP_CONVERGED,
    STOP_FOCUS_CLARIFIED,
    STOP_RED_TEAM_EXHAUSTED,
    DebateClash,
    DebateConfig,
    DebateForm,
    DebateSide,
    JudgeVerdict,
    RoundPolicy,
    RoundResult,
    SideTurn,
)

# 金标 stop_reason 只允许「收敛类」取值（max_rounds / all_failed / user_concluded 是循环层归因，
# 非裁判判收敛时给的）——lint 据此校验 expect_stop。
_CONVERGED_STOPS = frozenset({STOP_CONVERGED, STOP_FOCUS_CLARIFIED, STOP_RED_TEAM_EXHAUSTED})


@dataclass(frozen=True)
class PriorRound:
    """账本里的一条前轮记录 —— 收敛校准 §三 H2 的【跨轮】输入。

    喂进 ``moderator._prior_ledger`` 的紧凑摘要：``focus`` 本轮议题、``summary`` 本轮小结、
    ``clashes`` 交锋边 ``(from_key, to_key, point)``。裁判据这份「已辩论点账本」判当前轮是否还有
    跨轮新论点。
    """

    focus: str
    summary: str
    clashes: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class ConvergeScenario:
    """一个带金标的单轮辩论态 —— 收敛校准的「合成样本」。

    ``turns`` 是【当前轮】各方发言；``prior_rounds`` 是喂裁判的【前几轮论点账本】（收敛校准 §三
    H2：裁判据此判跨轮新论点，见 ``moderator._prior_ledger``）——留空则退化为「只看当前轮」
    （in-round 敏感度）。``round_no`` / ``max_rounds`` / ``thorough`` 决定裁判的 gate_hint 语境
    （首轮默认继续、快速单轮即收、thorough 调松紧）。``expect_converge`` 是金标：本轮据【账本 +
    当前发言】是否应当收敛；``expect_stop`` 是可选金标收敛归因（仅 ``expect_converge`` 为真时有
    意义）。``why`` 记金标理由，便于读分歧时对照裁判为何与金标不一致。
    """

    id: str
    form: DebateForm
    motion: str
    sides: tuple[DebateSide, ...]
    focus: str
    round_no: int
    max_rounds: int
    thorough: bool
    turns: tuple[SideTurn, ...]
    expect_converge: bool
    why: str
    expect_stop: str = ""
    prior_rounds: tuple[PriorRound, ...] = ()

    def config(self) -> DebateConfig:
        """据场景构造生产 `DebateConfig`（policy 用 thorough + max_rounds，喂裁判 gate_hint）。"""
        return DebateConfig(
            motion=self.motion,
            form=self.form,
            sides=list(self.sides),
            policy=RoundPolicy(thorough=self.thorough, max_rounds=self.max_rounds),
        )

    def history(self) -> list[RoundResult]:
        """构造 ``round_no - 1`` 条历史轮 —— 定 round_no（长度）+ 喂裁判的【跨轮论点账本】。

        给了 ``prior_rounds`` 时用其真实 focus/summary/clashes 建轮（收敛校准 §三 H2：账本进裁判
        判据，测跨轮收敛）；未给时退化为最小占位轮（summary/clashes 空 → 账本空 → 裁判只看当前轮，
        测 in-round 敏感度）。
        """
        if self.prior_rounds:
            out: list[RoundResult] = []
            for i, pr in enumerate(self.prior_rounds, start=1):
                clashes = [DebateClash(from_key=f, to_key=t, point=p) for f, t, p in pr.clashes]
                verdict = JudgeVerdict(
                    real_clash=True, new_arguments=True, converged=False, clashes=clashes
                )
                out.append(RoundResult(i, pr.focus, [], verdict, summary=pr.summary))
            return out
        placeholder = JudgeVerdict(real_clash=True, new_arguments=True, converged=False)
        return [
            RoundResult(i, f"（第 {i} 轮焦点）", [], placeholder, summary="")
            for i in range(1, self.round_no)
        ]


def _side(key: str, name: str, stance: str, *, is_subject: bool = False) -> DebateSide:
    return DebateSide(key=key, name=name, stance=stance, is_subject=is_subject)


def _turn(key: str, name: str, content: str) -> SideTurn:
    return SideTurn(side_key=key, side_name=name, run_id=f"{key}_turn", content=content, ok=True)


# --- 合成场景集（金标）------------------------------------------------------
# 每个场景的【当前轮发言】自身就带足金标信号（因裁判只看当前轮，见模块 docstring）：
# 该收敛的场景里发言明说「无新论点 / 只是价值取舍 / 挖不到新风险」；该继续的场景里发言引入
# 明确的实质新论点 / 新视角 / 新风险。刻意做成清晰无歧义的范例——量的是裁判对这些信号的敏感度。

_S_DEBATE = DebateForm.DEBATE
_S_RED = DebateForm.RED_TEAM
_S_ROUND = DebateForm.ROUNDTABLE

SCENARIOS: tuple[ConvergeScenario, ...] = (
    # ── 该收敛（若裁判判「继续」= over-conservatism，本盘点主信号）──────────────
    ConvergeScenario(
        id="plateau_repeat",
        form=_S_DEBATE,
        motion="公司该不该全面转向远程办公",
        sides=(
            _side("pro", "正方", "支持全面远程办公"),
            _side("con", "反方", "反对全面远程办公"),
        ),
        focus="远程办公对协作效率的净影响",
        round_no=3,
        max_rounds=5,
        thorough=True,
        turns=(
            _turn(
                "pro",
                "正方",
                "我方立场与前两轮完全一致：远程省通勤、扩大人才池、提升专注度。这些前面已充分"
                "论证，本轮没有新的论据要补充，反方的顾虑我们上一轮也回应过了。",
            ),
            _turn(
                "con",
                "反方",
                "我方同样是重复前两轮的核心：协作损耗、文化稀释、管理难度上升。确实没有新论点"
                "可加了，双方其实已经把该说的都说完，只是在原地打转。",
            ),
        ),
        expect_converge=True,
        expect_stop=STOP_CONVERGED,
        why="双方本轮均明说无新论点、只重复此前立场（new_arguments 应为 false），已达收敛点。",
    ),
    ConvergeScenario(
        id="value_impasse",
        form=_S_DEBATE,
        motion="有限工期下产品先做深色模式还是无障碍支持",
        sides=(
            _side("dark", "深色优先派", "主张先做深色模式"),
            _side("a11y", "无障碍优先派", "主张先做无障碍支持"),
        ),
        focus="有限工期下先做哪个",
        round_no=2,
        max_rounds=5,
        thorough=True,
        turns=(
            _turn(
                "dark",
                "深色优先派",
                "到这一步已经不是事实之争了：两个功能技术上都能做、成本相近；先做哪个纯粹取决于"
                "你更看重『多数用户的日常体验』还是『少数用户的可及性』——这是价值排序，无所谓对错。",
            ),
            _turn(
                "a11y",
                "无障碍优先派",
                "同意对方，本轮我们其实已达成共识：剩下的分歧只是价值权重。我个人坚持无障碍是底线"
                "义务，但这确实是你们的价值取舍，再辩下去也不会有新的事实性论据。",
            ),
        ),
        expect_converge=True,
        expect_stop=STOP_FOCUS_CLARIFIED,
        why="分歧已归结为纯价值/优先级取舍（双方都承认无事实可裁）"
        "——正是 focus_clarified 收敛信号。",
    ),
    ConvergeScenario(
        id="red_team_exhausted",
        form=_S_RED,
        motion="压力测试：新版限流方案的漏洞",
        sides=(
            _side("plan", "方案方", "为新版限流方案辩护并修补", is_subject=True),
            _side("red", "红队", "尽力挖新版限流方案的漏洞与失败场景"),
        ),
        focus="剩余未覆盖的失败场景",
        round_no=3,
        max_rounds=5,
        thorough=True,
        turns=(
            _turn(
                "plan",
                "方案方",
                "前两轮红队提的三类风险（突发流量、依赖抖动、配置漂移）我们都已给出修补并说明。"
                "本轮红队没有指出新的攻击面。",
            ),
            _turn(
                "red",
                "红队",
                "我方尽力再找，但确实没挖到新的失败场景了——之前提的都已被合理修补。到此风险面"
                "基本挖尽，没有新的漏洞可攻。",
            ),
        ),
        expect_converge=True,
        expect_stop=STOP_RED_TEAM_EXHAUSTED,
        why="红队明说挖不到新风险、方案方已修补此前所有风险（无新风险可挖）——红队形态收敛信号。",
    ),
    ConvergeScenario(
        id="quick_single",
        form=_S_DEBATE,
        motion="午饭吃火锅还是烤肉",
        sides=(
            _side("hotpot", "火锅党", "主张吃火锅"),
            _side("bbq", "烤肉党", "主张吃烤肉"),
        ),
        focus="今天中午吃哪个更合适",
        round_no=1,
        max_rounds=1,
        thorough=False,
        turns=(
            _turn("hotpot", "火锅党", "火锅：食材灵活、锅底可选、一群人围着热闹，冬天尤其合适。"),
            _turn("bbq", "烤肉党", "烤肉：不用等煮、上桌快、有专人烤、蛋白质管够。"),
        ),
        expect_converge=True,
        expect_stop=STOP_CONVERGED,
        why="快速单轮（max=1）：用户只想一次对碰即收，核心立场已亮出即应收敛"
        "（否则错误兜底 max_rounds）。",
    ),
    ConvergeScenario(
        id="plateau_reword",
        form=_S_DEBATE,
        motion="该不该给核心服务引入缓存层",
        sides=(
            _side("pro", "正方", "支持引入缓存层"),
            _side("con", "反方", "反对引入缓存层"),
        ),
        focus="缓存一致性风险 vs 性能收益",
        round_no=4,
        max_rounds=5,
        thorough=True,
        turns=(
            _turn(
                "pro",
                "正方",
                "再强调一次性能收益、换个说法而已：缓存把 p99 从 800ms 降到 120ms，这个量级前面"
                "已经算过，本轮只是换个角度重述同一件事，没有新机制。",
            ),
            _turn(
                "con",
                "反方",
                "我也还是那个一致性顾虑，只是这轮换个例子说：失效窗口内的脏读风险依旧，本质和我"
                "第 2 轮讲的是同一个问题，没有引入新的论据。",
            ),
        ),
        expect_converge=True,
        expect_stop=STOP_CONVERGED,
        why="双方只是把同一论点换措辞重述（换汤不换药、自承无新机制），new_arguments 实为 false。",
    ),
    # ── 该继续（若裁判判「收敛」= premature，反向错误）──────────────────────────
    ConvergeScenario(
        id="round1_opening",
        form=_S_DEBATE,
        motion="该不该推行四天工作制",
        sides=(
            _side("pro", "正方", "支持四天工作制"),
            _side("con", "反方", "反对四天工作制"),
        ),
        focus="四天工作制对整体产出的影响",
        round_no=1,
        max_rounds=5,
        thorough=True,
        turns=(
            _turn(
                "pro",
                "正方",
                "四天工作制提升专注与幸福感，欧洲多地试点显示产出不降反升，"
                "还能降低 burnout 与离职率。",
            ),
            _turn(
                "con",
                "反方",
                "但客户响应窗口、跨时区协作、按时薪计酬的岗位都会受影响；试点样本也多是知识型白领，"
                "不能一概而论。",
            ),
        ),
        expect_converge=False,
        why="第 1 轮各方刚亮出立论、尚未真正接火（round-1 默认继续以逼出下一轮真交锋），不应收敛。",
    ),
    ConvergeScenario(
        id="new_strong_argument",
        form=_S_DEBATE,
        motion="创业公司该全上云还是自建 IT 基础设施",
        sides=(
            _side("cloud", "全上云派", "主张全部上公有云"),
            _side("onprem", "自建派", "主张自建基础设施"),
        ),
        focus="成本与可控性的长期权衡",
        round_no=2,
        max_rounds=5,
        thorough=True,
        turns=(
            _turn(
                "cloud",
                "全上云派",
                "继续主张全上云：免运维、弹性伸缩、按需付费，创业早期最省心。",
            ),
            _turn(
                "onprem",
                "自建派",
                "本轮我要提一个前面没谈过的新点：月活过百万后云账单会越过自建总成本的临界点"
                "（我们测算约 18 个月回本）；更关键的是数据主权与合规审计——部分客户合同强制要求"
                "数据不出自有机房，这是全上云根本满足不了的。",
            ),
        ),
        expect_converge=False,
        why="反方引入此前未涉及的实质新论点（成本临界点 + 数据主权/合规），"
        "正方尚未回应，仍有新论点。",
    ),
    ConvergeScenario(
        id="roundtable_new_perspective",
        form=_S_ROUND,
        motion="如何看待 AI 生成内容对创作行业的影响",
        sides=(
            _side("tool", "工具论视角", "AI 是创作放大器"),
            _side("labor", "劳动分配视角", "关注创作者生计与收益分配"),
            _side("ethic", "法律伦理视角", "关注版权与创作伦理"),
        ),
        focus="AI 生成内容影响的核心维度",
        round_no=2,
        max_rounds=4,
        thorough=True,
        turns=(
            _turn("tool", "工具论视角", "AI 是放大器，降低创作门槛、让更多人能表达。"),
            _turn(
                "labor",
                "劳动分配视角",
                "但它冲击的是中腰部创作者的生计，收益进一步向平台与头部集中。",
            ),
            _turn(
                "ethic",
                "法律伦理视角",
                "本轮我补一个前面没人谈的维度：训练数据的版权来源与署名权——这不是效率或分配问题，"
                "而是创作伦理与法律根基问题。",
            ),
        ),
        expect_converge=False,
        why="圆桌本轮刚冒出一个前面未谈的独特视角（版权/创作伦理），观点光谱尚未铺满，不应收敛。",
    ),
    ConvergeScenario(
        id="red_team_new_risk",
        form=_S_RED,
        motion="压力测试：用户注册流程的安全性",
        sides=(
            _side("plan", "方案方", "为注册流程辩护并修补", is_subject=True),
            _side("red", "红队", "挖注册流程的安全漏洞"),
        ),
        focus="尚未覆盖的攻击面",
        round_no=2,
        max_rounds=5,
        thorough=True,
        turns=(
            _turn(
                "plan",
                "方案方",
                "针对第 1 轮红队提的弱口令问题，我们已加强密码策略并对尝试加限流。",
            ),
            _turn(
                "red",
                "红队",
                "本轮我提一个新的、更严重的攻击面：注册接口未防枚举——攻击者可据『邮箱已注册』的"
                "差异化响应批量探测用户是否存在，配合撞库形成账户接管链路。这与上一轮的弱口令是"
                "不同类别、且尚未修补的风险。",
            ),
        ),
        expect_converge=False,
        why="红队本轮挖出一类此前未涉及、且未被修补的新风险（枚举 → 账户接管），仍有新风险可挖。",
    ),
    # ── 跨轮账本（H2：信号在 prior_rounds、当前轮不自报，须靠跨轮账本才判得对）──────────
    ConvergeScenario(
        id="crossround_reword",
        form=_S_DEBATE,
        motion="公司该不该全面转向远程办公",
        sides=(
            _side("pro", "正方", "支持全面远程办公"),
            _side("con", "反方", "反对全面远程办公"),
        ),
        focus="远程办公的净影响",
        round_no=3,
        max_rounds=5,
        thorough=True,
        prior_rounds=(
            PriorRound(
                focus="远程办公对个人产出的影响",
                summary="正方主张远程省通勤、扩大人才池、提升专注；反方主张远程带来协作损耗、"
                "文化稀释、管理难度上升。",
                clashes=(
                    ("pro", "con", "通勤时间省下来直接转化为产出"),
                    ("con", "pro", "异步协作的沟通损耗抵消了专注收益"),
                ),
            ),
            PriorRound(
                focus="远程办公对团队协作的影响",
                summary="正方称工具已能支撑异步协作，反方称临场脑暴不可替代——协作维度已充分展开。",
                clashes=(("con", "pro", "工具替代不了面对面的高带宽脑暴"),),
            ),
        ),
        turns=(
            _turn(
                "pro",
                "正方",
                "远程办公最大的好处还是省下通勤、把人才池扩到全国，员工也更能专注——这几点让"
                "整体产出是提升的。",
            ),
            _turn(
                "con",
                "反方",
                "我还是认为面对面协作效率更高、团队文化更容易维系，管理者也更好带团队，这些是"
                "远程替代不了的。",
            ),
        ),
        expect_converge=True,
        expect_stop=STOP_CONVERGED,
        why="当前轮双方只是把账本里已有的老论点（省通勤/扩人才池/专注 vs 协作/文化/管理）换措辞"
        "重述、无一新论点，且未自报重复——须靠跨轮账本才判得出收敛。",
    ),
    ConvergeScenario(
        id="crossround_genuine_new",
        form=_S_DEBATE,
        motion="创业公司该全上云还是自建 IT 基础设施",
        sides=(
            _side("cloud", "全上云派", "主张全部上公有云"),
            _side("onprem", "自建派", "主张自建基础设施"),
        ),
        focus="成本与可控性的长期权衡",
        round_no=2,
        max_rounds=5,
        thorough=True,
        prior_rounds=(
            PriorRound(
                focus="早期成本与运维负担",
                summary="全上云派主张免运维、弹性伸缩、按需付费；自建派主张长期账单更低、硬件可控。",
                clashes=(("cloud", "onprem", "早期自建的固定投入拖垮现金流"),),
            ),
        ),
        turns=(
            _turn("cloud", "全上云派", "继续主张全上云：免运维、弹性伸缩、按需付费，早期最省心。"),
            _turn(
                "onprem",
                "自建派",
                "本轮我提一个账本里没有的新点：部分客户合同强制要求【数据不出自有机房】——这是"
                "数据主权与合规审计问题，全上云根本满足不了，和之前谈的成本是两码事。",
            ),
        ),
        expect_converge=False,
        why="自建派本轮引入账本里没有的实质新论点（数据主权/合规），非老论点重述——仍有跨轮新论点，"
        "不应收敛。",
    ),
    ConvergeScenario(
        id="crossround_redteam_reword",
        form=_S_RED,
        motion="压力测试：新版限流方案的漏洞",
        sides=(
            _side("plan", "方案方", "为新版限流方案辩护并修补", is_subject=True),
            _side("red", "红队", "尽力挖新版限流方案的漏洞"),
        ),
        focus="剩余未覆盖的失败场景",
        round_no=3,
        max_rounds=5,
        thorough=True,
        prior_rounds=(
            PriorRound(
                focus="突发流量下的失效",
                summary="红队提出突发流量击穿限流；方案方以分级限流 + 排队降级修补。",
                clashes=(("red", "plan", "峰值下计数器竞态导致限流失准"),),
            ),
            PriorRound(
                focus="依赖抖动与配置漂移",
                summary="红队提出依赖抖动、配置漂移两类风险；方案方以熔断兜底 + 配置校验修补。",
                clashes=(("red", "plan", "配置漂移使阈值静默失效"),),
            ),
        ),
        turns=(
            _turn(
                "red",
                "红队",
                "我再想想突发流量这块：要是瞬时峰值特别高，限流计数是不是还可能有点不准？"
                "另外配置那块万一改错了会不会又失效？",
            ),
            _turn(
                "plan",
                "方案方",
                "这两点其实就是前两轮的峰值竞态和配置漂移，我们已用分级限流 + 配置校验覆盖，"
                "换个说法也还是同样的处置，没有新攻击面。",
            ),
        ),
        expect_converge=True,
        expect_stop=STOP_RED_TEAM_EXHAUSTED,
        why="红队本轮只把账本里已挖过的风险（峰值竞态/配置漂移）换措辞重提、无账本外新攻击面，"
        "方案方指出即旧风险——红队风险已挖尽，须靠跨轮账本判收敛。",
    ),
)


def lint_scenarios(scenarios: Sequence[ConvergeScenario] = SCENARIOS) -> None:
    """零 LLM 校验场景集结构（per-PR 硬门禁）：带病数据绝不开跑，与 gold-set loader 同口径。

    校验：id 唯一非空；≥2 方且 key 唯一；round_no 落在 ``[1, max_rounds]``；turns 非空且 side_key
    均属声明方；红队形态恰有 1 个 is_subject（其余形态无）；``expect_stop`` 仅收敛场景可给、且取
    收敛类归因；集合两侧均衡（至少各 2 条 converge / continue，否则混淆矩阵无意义）。违例 raise
    :class:`~agentcore.evals.types.EvalConfigError`。
    """
    if not scenarios:
        raise EvalConfigError("debate-converge 场景集为空")
    seen: set[str] = set()
    n_converge = 0
    n_continue = 0
    for sc in scenarios:
        if not sc.id:
            raise EvalConfigError("debate-converge 场景 id 不能为空")
        if sc.id in seen:
            raise EvalConfigError(f"debate-converge 场景 id 重复: {sc.id!r}")
        seen.add(sc.id)
        keys = [s.key for s in sc.sides]
        if len(sc.sides) < 2:
            raise EvalConfigError(f"[{sc.id}] 至少需要 2 个参与方")
        if len(set(keys)) != len(keys):
            raise EvalConfigError(f"[{sc.id}] 参与方 key 重复: {keys}")
        if sc.max_rounds < 1:
            raise EvalConfigError(f"[{sc.id}] max_rounds 需 >= 1")
        if not 1 <= sc.round_no <= sc.max_rounds:
            raise EvalConfigError(
                f"[{sc.id}] round_no={sc.round_no} 须落在 [1, max_rounds={sc.max_rounds}]"
            )
        if sc.prior_rounds and len(sc.prior_rounds) != sc.round_no - 1:
            raise EvalConfigError(
                f"[{sc.id}] prior_rounds 数 {len(sc.prior_rounds)} 须 == round_no-1 "
                f"({sc.round_no - 1})：账本轮数须与历史轮数一致"
            )
        if not sc.turns:
            raise EvalConfigError(f"[{sc.id}] 当前轮 turns 不能为空")
        valid_keys = set(keys)
        for t in sc.turns:
            if t.side_key not in valid_keys:
                raise EvalConfigError(f"[{sc.id}] turn 的 side_key={t.side_key!r} 不属于声明方")
            if not t.content.strip():
                raise EvalConfigError(f"[{sc.id}] 发言 {t.side_key} 内容为空")
        for pr in sc.prior_rounds:
            for frm, to, _point in pr.clashes:
                if frm not in valid_keys or to not in valid_keys:
                    raise EvalConfigError(
                        f"[{sc.id}] prior_rounds 交锋 side_key {frm!r}/{to!r} 不属于声明方"
                    )
        subjects = [s for s in sc.sides if s.is_subject]
        if sc.form is DebateForm.RED_TEAM and len(subjects) != 1:
            raise EvalConfigError(f"[{sc.id}] 红队形态须恰有 1 个 is_subject（现 {len(subjects)}）")
        if sc.form is not DebateForm.RED_TEAM and subjects:
            raise EvalConfigError(f"[{sc.id}] 非红队形态不应有 is_subject")
        if sc.expect_stop:
            if not sc.expect_converge:
                raise EvalConfigError(f"[{sc.id}] expect_stop 仅在 expect_converge=True 时有意义")
            if sc.expect_stop not in _CONVERGED_STOPS:
                raise EvalConfigError(
                    f"[{sc.id}] expect_stop={sc.expect_stop!r} 非收敛类归因 "
                    f"{sorted(_CONVERGED_STOPS)}"
                )
        if sc.expect_converge:
            n_converge += 1
        else:
            n_continue += 1
    if n_converge < 2 or n_continue < 2:
        raise EvalConfigError(
            f"场景两侧需均衡（各 >= 2）：现 converge={n_converge} / continue={n_continue}"
        )


# --- 校准结果 + 聚合 ---------------------------------------------------------


@dataclass
class ScenarioJudgement:
    """裁判在一个场景上的判定 vs 金标（逐条留痕，供算一致度 + 列分歧）。"""

    id: str
    form: str
    expect_converge: bool
    judge_converged: bool
    judge_new_arguments: bool
    expect_stop: str
    judge_stop_reason: str
    rationale: str
    why: str

    @property
    def correct(self) -> bool:
        """裁判收敛判定是否命中金标（收敛校准只看 converged 这一位）。"""
        return self.expect_converge == self.judge_converged

    @property
    def over_conservative(self) -> bool:
        """该收敛却判继续 —— over-conservatism（本盘点主关切）。"""
        return self.expect_converge and not self.judge_converged

    @property
    def premature(self) -> bool:
        """该继续却判收敛 —— 反向错误（过早收敛）。"""
        return (not self.expect_converge) and self.judge_converged


@dataclass
class ConvergeMetrics:
    """辩论收敛校准结果：混淆矩阵 + 两侧错误率 + 二分 kappa + 分歧样本。

    诊断性度量（非硬门禁）：目的是把「裁判是否系统性过保守」从 n=1 直觉变成可复跑信号，供
    「读分歧 → 判是否要调 `_judge` prompt」。样本合成、量小，读数只作方向参考（见报告小样本提示）。
    """

    per: list[ScenarioJudgement] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.per)

    @property
    def n_should_converge(self) -> int:
        return sum(1 for x in self.per if x.expect_converge)

    @property
    def n_should_continue(self) -> int:
        return sum(1 for x in self.per if not x.expect_converge)

    @property
    def accuracy(self) -> float:
        """裁判收敛判定命中金标的比例。"""
        return sum(1 for x in self.per if x.correct) / self.n if self.per else 0.0

    @property
    def over_conservative(self) -> list[ScenarioJudgement]:
        return [x for x in self.per if x.over_conservative]

    @property
    def premature(self) -> list[ScenarioJudgement]:
        return [x for x in self.per if x.premature]

    @property
    def over_conservatism_rate(self) -> float:
        """**主信号**：该收敛的场景里，裁判判「继续」的比例（越高越坐实过保守）。"""
        denom = self.n_should_converge
        return len(self.over_conservative) / denom if denom else 0.0

    @property
    def premature_rate(self) -> float:
        """反向错误率：该继续的场景里，裁判判「收敛」的比例。"""
        denom = self.n_should_continue
        return len(self.premature) / denom if denom else 0.0

    @property
    def cohens_kappa(self) -> float:
        """二分（收敛/继续）判↔金标一致度（复用 calibration.cohens_kappa，扣除偶然一致）。"""
        if not self.per:
            return 0.0
        a = [1 if x.expect_converge else 0 for x in self.per]
        b = [1 if x.judge_converged else 0 for x in self.per]
        return cohens_kappa(a, b)

    @property
    def disagreements(self) -> list[ScenarioJudgement]:
        """判↔金标不一致的场景（over-conservatism 排在 premature 前，先看主关切）。"""
        return sorted(
            (x for x in self.per if not x.correct),
            key=lambda x: (0 if x.over_conservative else 1, x.id),
        )


async def run_debate_converge(
    provider: LLMProvider,
    model: str,
    scenarios: Sequence[ConvergeScenario] = SCENARIOS,
) -> ConvergeMetrics:
    """对每个场景过**生产合并裁判** `_judge_and_summarize`，逐条收 (金标, 裁判收敛判定)，聚成
    :class:`ConvergeMetrics`。

    直接调 `Moderator._judge_and_summarize`（收敛校准的被测单元＝其【裁判判定】部分，小结弃）——与
    它在生产循环里被调用的入参一致：``(config, focus, 当前轮 turns, 历史)``，历史定 round_no + 小结
    锚点（见模块 docstring）。用合并后的真实生产路径校准，量到的即线上那把裁判。单测注入脚本化假
    provider，真模型留给手动 / nightly 校准。
    """
    if not scenarios:
        raise EvalConfigError("debate-converge 场景集为空，无法校准")
    mod = Moderator(provider=provider, model=model, scenario_prefix="eval.debate_converge")
    per: list[ScenarioJudgement] = []
    for sc in scenarios:
        # 合并裁判一次产出 (verdict, summary)；收敛校准只读裁判判定，小结弃。
        verdict, _summary = await mod._judge_and_summarize(
            sc.config(), sc.focus, list(sc.turns), sc.history()
        )
        per.append(
            ScenarioJudgement(
                id=sc.id,
                form=sc.form.value,
                expect_converge=sc.expect_converge,
                judge_converged=verdict.converged,
                judge_new_arguments=verdict.new_arguments,
                expect_stop=sc.expect_stop,
                judge_stop_reason=verdict.stop_reason,
                rationale=verdict.rationale,
                why=sc.why,
            )
        )
    return ConvergeMetrics(per=per)


def _debate_provider_and_model(mode: str = "quality") -> tuple[LLMProvider, str]:
    """构造接真实 DeepSeek 的辩论裁判 (provider, model) —— 与生产辩论同 ``agent`` profile。

    生产辩论主持人用 ``profile_set.agent().model``（DebateTool），故校准也取同一 profile 以
    量到【真实同一把裁判】；可经 ``EVAL_DEBATE_MODEL`` 显式覆写。凭据/ceiling 复用 eval 专用解析
    （与 judge.py 同源）。惰性 import 重依赖，保持本模块顶层轻。
    """
    import os

    from agentcore.evals.eval_modes import resolve_profile_set
    from agentcore.evals.harness import _EVAL_CEILING, _eval_credentials
    from agentcore.llm.factory import build_provider

    provider = build_provider(_eval_credentials())
    model = os.environ.get("EVAL_DEBATE_MODEL", "").strip()
    if not model:
        profiles = resolve_profile_set(mode, custom_modes={}, ceiling=_EVAL_CEILING)
        model = profiles.agent().model
    return provider, model


# --- 序列化 + 控制台报告（与 calibration.py / routing.py 风格一致：ASCII 标记防乱码）----


def debate_converge_to_dict(m: ConvergeMetrics) -> dict:
    """JSON-able dict（落盘 / 趋势对比；与 calibration_to_dict 风格一致）。"""
    return {
        "n": m.n,
        "n_should_converge": m.n_should_converge,
        "n_should_continue": m.n_should_continue,
        "accuracy": round(m.accuracy, 4),
        "over_conservatism_rate": round(m.over_conservatism_rate, 4),
        "premature_rate": round(m.premature_rate, 4),
        "cohens_kappa": round(m.cohens_kappa, 4),
        "per_scenario": [
            {
                "id": x.id,
                "form": x.form,
                "expect_converge": x.expect_converge,
                "judge_converged": x.judge_converged,
                "judge_new_arguments": x.judge_new_arguments,
                "expect_stop": x.expect_stop,
                "judge_stop_reason": x.judge_stop_reason,
                "correct": x.correct,
                "rationale": x.rationale,
                "why": x.why,
            }
            for x in m.per
        ],
    }


def format_debate_converge_report(m: ConvergeMetrics) -> str:
    """控制台文本：混淆矩阵 + 两侧错误率 + kappa + 分歧逐条。ASCII 标记避免 Windows 乱码。"""
    lines: list[str] = ["=" * 68, "AgentCore 辩论收敛校准（裁判判定 ↔ 金标）", "=" * 68]
    lines.append(
        f"  场景 {m.n}    该收敛 {m.n_should_converge}    该继续 {m.n_should_continue}"
    )
    if m.n < 20:
        lines.append(f"  [!] 合成样本仅 {m.n} 条，读数只作方向参考、勿据此过拟合调裁判（§三）")
    lines.append("-" * 68)
    lines.append(f"  准确率(收敛判定命中金标)   {m.accuracy * 100:.0f}%")
    lines.append(
        f"  过保守率(该收敛却判继续)   {m.over_conservatism_rate * 100:.0f}%"
        f"  [{len(m.over_conservative)}/{m.n_should_converge}]  <- 本盘点主信号"
    )
    lines.append(
        f"  过早收敛率(该继续却判收敛) {m.premature_rate * 100:.0f}%"
        f"  [{len(m.premature)}/{m.n_should_continue}]"
    )
    lines.append(f"  Cohen's kappa(判↔金标)      {m.cohens_kappa:.3f}")
    dis = m.disagreements
    if dis:
        lines.append("-" * 68)
        lines.append(f"  判↔金标分歧 {len(dis)} 条（过保守优先·读分歧定是否要调 _judge）:")
        for x in dis:
            kind = "过保守" if x.over_conservative else "过早收敛"
            exp = "收敛" if x.expect_converge else "继续"
            got = "收敛" if x.judge_converged else "继续"
            lines.append(f"    [{x.id}] {kind}：金标={exp} 判={got}")
            lines.append(f"        金标理由：{x.why[:56]}")
            lines.append(f"        裁判理由：{x.rationale[:56]}")
    else:
        lines.append("-" * 68)
        lines.append("  无分歧：裁判在本合成集上的收敛判定与金标完全一致。")
    lines.append("=" * 68)
    return "\n".join(lines)
