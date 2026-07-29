"""System Skills: code-defined capability docs the CEO pulls on demand (渐进披露).

提示词瘦身 P2 的落地。CEO 的常驻系统提示词只保留「决定干什么」的路由核心（见
``prompt._CEO_CORE_HINT``）；「怎么干」的进阶机制——团队编排进阶 / 辩论与交叉审查 /
定向唤回 / 向用户发问（开场提案卡 + 途中拍板）/ 委派波间挂起——下沉为 **系统 Skill**：代码定义、随 CEO 常备、以一
张「能力目录」常驻（仅一行触发描述），模型决定要用某能力后才用 ``consult_skill(name)``
把完整指引拉回自己的 ReAct 循环。

这是 ``docs/03-AI核心/工具与能力系统.md §二`` 已定的「Skill 渐进披露」机制（目录模式 +
按名拉取）的第一个实例。系统 Skill 与未来「市场 Skill」并列为两类来源，共用同一套
``SkillRegistry`` + ``consult_skill``（单一机制、多类来源）——正如内置工具与市场工具
共用 ``ToolRegistry``，不另造平行系统。

``requires_tools`` 把现有的 live-user 门（ask_user 仅在有活跃用户时装配）一般化：一个
Skill 只在它依赖的工具全部装配时才进目录，故提示词永不广告 CEO 手里没有的能力（沿用
现有不变量）。

维护约定（防双源漂移）：各 Skill 的 ``body`` 是**面向模型的 HOW 操作指引**的单一真相源；
``docs/03-AI核心`` 各专题只写设计意图与约束（What/Why），不逐字复述 body。改动编排行为时
两处同步：行为语义以设计文档为准，喂给模型的措辞以本文件为准。
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

from agentcore.runtime.coordination.session import (
    DEFAULT_COORDINATION_BUDGET,
    MAX_COORDINATION_BUDGET,
)
from agentcore.runtime.runs.playbooks import PLAYBOOKS, available_playbooks
from agentcore.workspace.stage_dirs import RESEARCH_DIR, REVIEWS_DIR

# playbook 降级为形状词汇教学示例（协作优先重设计阶段 2）：listing 仍嵌进 skill，口径改为对照学形状。
_PLAYBOOK_LISTING = available_playbooks()
_BUILD_WEBSITE_PLAYBOOK = PLAYBOOKS["build_website"]
_BUILD_TOOLSHED_PLAYBOOK = PLAYBOOKS["build_toolshed"]
_BUILD_APP_PLAYBOOK = PLAYBOOKS["build_app"]

# 多维取证类终局对抗触发词（kickoff research_first_recommended + MLR/debate 入口分流句同源，禁止另抄字面量）。
MULTI_LENS_COURTROOM_TRIGGERS: Final[tuple[str, ...]] = (
    "模拟法庭",
    "庭审对抗",
    "对簿公堂",
)
_MULTI_LENS_COURTROOM_TRIGGERS_JOINED = "/".join(MULTI_LENS_COURTROOM_TRIGGERS)

# Shared with ``prompt._CEO_CORE_HINT`` — same intensity, no「可选 vs 必先查」对打.
CONSULT_TEAM_ORCH_BY_SCENE = (
    "按场面：建站/工具台套 playbook、或拿不准怎么拆 → 必查 `team_orchestration_advanced`；"
    "常见对比 / 单人落盘 / 提问卡 → 直接做不必查；单人事清楚可 finalize → 可不查"
)


@dataclass(frozen=True)
class SystemSkill:
    """One code-defined capability doc, surfaced in the catalog and pulled by consult.

    ``summary`` is the one-line trigger description shown in the always-on catalog
    (tells the model WHEN to pull it); ``body`` is the full HOW guidance, returned
    only when ``consult_skill(name)`` is called. ``requires_tools`` gates the
    catalog entry: the skill appears only when every named tool is wired this turn
    (e.g. the ``ask_user_*`` skills need the ``ask_user`` tool, which is live-user
    only), so the prompt never advertises a capability the CEO cannot act on.
    """

    name: str
    summary: str
    body: str
    requires_tools: tuple[str, ...] = ()


class SkillRegistry:
    """Name → :class:`SystemSkill` lookup (single source of truth, mirrors ToolRegistry)."""

    def __init__(self) -> None:
        self._skills: dict[str, SystemSkill] = {}

    def register(self, skill: SystemSkill) -> None:
        """Register a skill. Raises ValueError if the name is already registered."""
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' is already registered")
        self._skills[skill.name] = skill

    def get(self, name: str) -> SystemSkill | None:
        """Resolve a skill by name, or None if unknown (consult_skill degrades on miss)."""
        return self._skills.get(name)

    def list_all(self) -> list[SystemSkill]:
        """Every registered skill (registration order)."""
        return list(self._skills.values())

    def available(self, tool_names: set[str]) -> list[SystemSkill]:
        """Skills whose ``requires_tools`` are all wired — the catalog visibility filter."""
        return [
            skill
            for skill in self._skills.values()
            if all(tool in tool_names for tool in skill.requires_tools)
        ]


# --- System Skill bodies (the HOW guidance, moved out of the always-on prompt) ---
# Each was a CEO hint in runtime/resolve/prompt.py (P1); P2 externalises them so they ride
# the context only when the CEO consults them. Wording preserved so behavior is
# unchanged — only the delivery (always-on → on-demand) differs.

_TEAM_ORCHESTRATION_ADVANCED = """\
<team_orchestration_advanced>
实质任务该派就派。按活的**自然缝**拆人，不按工种表凑人；能少则少，真并行再多；\
拿不准先少派。先想形状再拆任务——教的是【词汇 + 组合】，不是成品模板。\
自检：换个主题，形状还一模一样吗？还一样就错了。\
「调研+写码+点评+合成一篇」这类跨域合成流水线 → 常见 1～2 人，勿默认每人一种专长；\
成篇落盘的【产出→独立审校】是质量缝、不算凑工种，默认保留。\
「先设计再实现」小CRUD/骨架 → 默认 1 人两段（先交设计验收再实现）；设计很重或要点名评审再升 2 人串。

形状词汇（按任务结构选、可组合）：
- 并列对象分组：每对象一员（重档升 lead 内拆维度），尾挂横向汇总；\
用户点名 ≥2 个实体对比 / 选型 → **tasks 人数 ≥ 实体数**（可 +1 汇总），禁止 1 人包办；\
禁止以「综合写一份更合适」降到单人
- 角度扇出：N 角度并行调研 / 产出，汇入下游
- 证据驱动流水线：调研 → 结构定稿（主拍板）→ 产出
- 独立审查：审查者 ≠ 作者，产出结构化问题清单
- 有界返工环：审查发现 → 原作者带现场续派修订 → 复核，≤2 轮，到限交代缺口；\
修订按审校意见逐条用 `str_replace` 局部改（优先）、扩写用 `file_append`；\
整文件 `file_write` 覆盖允许但勿惰性省略中段（反例：「……（中间省略，已保留首尾）……」致残缺交付）
- 契约共享面：wall + seed_notes 播种口径 / 接口 / 约束，decision 便签广播
- 独立多透镜诊断：对既有材料 N 透镜并审 → 风险分级汇总 → 风险确认卡\
（`ask_user` 带 `card="risk_ack"`）让用户勾选要处理项 → 定向修订
- 部件一致性对账：并行部件起草 → 对账节点专查接缝 → 定向修订
- 对抗辩论：Moderator 驱动交锋；其他原型真冲突才开局部辩（勿默认冲突即辩）
- 发散挑选：N 风格并行 →（轻量互评）→ 方案挑选卡（`ask_user` 带 `card="proposal_pick"`）\
让用户挑一个 → 中选深化

组合：多对象+成篇 → 分组×流水线；构建+并行模块 → 契约共享面+独立验证；\
审查要改 → 接有界返工环；结论真冲突 → 局部辩论；跨域合成一篇 → 少派串起，勿按工种堆人。

三档：默认中档。轻=保底（构建类轻档也要「实现+独立验证」双人）；\
重=任务规模大或用户点名才上。控税靠选档与按缝拆人，不靠默认单干、也不按工种凑满。

教学示例形状（playbook）：下列是词汇表的可实例化示例——对照学形状，勿「是就直接套」。\
形态贴合时可设 `playbook` + `playbook_args` 生成骨架（与手写 tasks 二选一）；否则按词汇手写。\
【自由组队】可不声明 playbook，直接手写 `tasks`。\
建站 / 工具台 / 绿场软件【推荐】具名 playbook（见 consult `build_website` / \
`build_toolshed` / `build_app`）；手写 / `none` 不再硬拒，勿在此复读全文。\
【成篇调研】要落盘的中篇实务/研究报告/论文且尚需 ≥2 可并行取证角 → 【宜】\
`research_report`（内含末环审校；禁止一人自搜+成文）；手写同构须齐【各角调研/讨论笔记 + \
主笔终稿 + 独立审校】：各角与主笔均 `form=files`+钉死 `artifacts`（可落 `""" + f"{RESEARCH_DIR}/" + """` 或同构目录）；\
末节点审校 `depends_on` 撰稿（role 含审校/审计/审查，审计者≠作者）——\
【禁止】仅「调研→撰稿」两节点收工；【禁止】「角 prose、仅主笔落盘」（中途停则用户零文件）。\
材料已齐扩写 / 短文落盘仍单人（成篇落盘仍【宜】另派独立审校）。\
本地修码：【无先验调查批】单文件/单符号一刀切 → 宜显式 `complexity_hint=light`+短任务（可 \
`requires_files`）；有复现症状 / 多点 / 需验 → `repair_code`（单症状三波；`playbook_args` 必填 \
`problem` + `verify`）。【已有多角调查/审查批、用户确认按结论修】→ **禁止**再套 \
`repair_code` 冷开新三角色；手写 tasks + 对各调查 run 设 `continue_from_run_id`（可并行；\
可改 task 正文/title，换马甲≠换职能；可声明超集 tools 只增不减）。\
**禁止**把 `none` 当修码默认、禁止触顶后再派马甲从零读。\
可用：""" + _PLAYBOOK_LISTING + """。槽位见 `delegate` 的 playbook_args。

按需用好 `delegate` 的进阶旋钮（不必都填）：

- 预算（统一 backstop）：worker 的 token 顶 / 墙钟 / 检索次数有统一安全阀（全员同额，\
不可按 task 配置检索额度）。墙钟若仍不够，可在该 task 里显式传 `timeout_ms`（毫秒）覆盖。
- 质量契约：对产出有硬性要求（须含某些小标题 / 关键词、限定格式）时用 `deliverable` \
声明——未达标会带着具体差距自动返工一次；返工后仍不达标默认仅附质检提醒（软），\
`deliverable.strict=true` 则判该 worker 失败（硬退）。`deliverable.name` 描述想要的产出形态。\
格式要求【只写在 deliverable】，task 正文不要再复述「输出 JSON / 必含章节」等格式条款。\
官网 / 营销文案类【优先】`required_sections` 结构化板块验收，【不要】用高 `min_length` \
字数门槛冒充质量门；关键词素材覆盖可设 `must_contain` 并接受软提醒，勿堆机构名硬门槛。\
**【must_contain 纪律】**只写交付物本体必须出现的主题词 / 结论要素；【禁止】把机构名、数据源名、\
报告标题等「取证路径」词塞进 `must_contain`——调研找到同级替代源也该算达标。反例：把 \
Stanford / McKinsey / Buffer / Owl Labs 写成硬门槛，会因未命中字面词连败假失败（内容其实已达标）。\
**【required_sections 纪律】**是验收点不是章节骨架——只留 2–4 个真验收项（如「证据」「结论」），\
结构细节留给 worker；勿把七维大纲整表塞进 `required_sections` 当蓝图（与下条「约束 vs 方案」同旨）。
- 审查类任务的统一契约（派【审查 / 质检 / 评审】worker 时【必设 deliverable】）：无论并行扇出\
还是 `depends_on` 链下游，每个审查官 task 都必须带 `deliverable` 锁定统一输出形态——否则各审查官\
各说各的、打分维度各异，你收工时难对齐。**【默认 prose】**（多路并行时各官 deliverable 完全一致，\
只换 role 与审查侧重）：\
`deliverable: { "form": "prose", "required_sections": ["问题", "建议", "评分"], \
"name": "审查意见（含问题 / 建议 / 评分）" }`。\
task 正文只给【被审材料的文件路径或引用】+【本官审查焦点】，【不要】把协议 / 原文全文复制进多个\
并行 task，也【不要】在 task 里再写一遍格式要求。审查 / 分析类优先依据已有原文材料，确有必要才\
`web_search`。审查默认是中间产物、注入下游或供你汇总：prose 批不设 `requires_files`。
- 结构化交付走文件通道（仅当下游真需字段级机械合并时才用 JSON）：worker 把 JSON 写入工作区文件，\
契约验「文件存在 + 可解析」。形态示例：\
`deliverable: { "form": "files", "output_format": "json", "artifacts": ["\
""" + f"{REVIEWS_DIR}/legal.json" + """"], \
"name": "JSON 对象，必含 problems（含 severity/description/evidence）/ suggestions / score（0–10）" }`\
——`artifacts` 对账路径存在，`output_format=json` 校验该文件可解析；聊天正文不必再贴一份 JSON。\
【禁止】把 `output_format=json` 与 `required_sections` 混用（后者是 Markdown 小标题语义，混用会假失败）。
- 依赖流水线（派前先判生产者→消费者）：拆出多任务后先逐对判「下游是否要吃上游产出」——要据上游的\
设计 / 接口 / 结论 / 落盘文件才能开工 → 串行，用【同一次 `delegate`】里的 `depends_on` 串成依赖图；\
彼此不吃对方产出 → 留空 `[]` 平铺并行。【正例·串行】设计规范 + 内容策略 → 前端实现（前端 depends_on \
两者）、调研 → 提纲 → 成文逐级依赖、后端接口 → 前端页面 ‖ 测试（后两者各 depends_on 接口）；\
【反例·勿串】多实体各查一份 / N 风格各起一稿 / 互不引用的独立部件 → 各留空并行，别硬加依赖拖慢。\
检查点波（`checkpoint_after`）通过后，中段若彼此不吃对方产出，应扇出而非再串成单链——可设 \
`parallelism=balanced`（默认 conservative 不改图）：保留检查点后第一跳，其后可并行再汇合。\
漏判把有先后的活拍成全平铺，下游会空手 / 缺上游产物开工、各自重造、烧穿预算。\
多阶段（设计 → 实现 → 审查）这些 worker 都在你下面【同一层】，上游产出自动注入下游；`depends_on` 只定先后、\
不加层级。DAG 模式下每个 task 必须显式声明 `depends_on`（即使为空列表 `[]`）。如果 task \
描述中提到「上游」「基于…产出」，必须对应 `depends_on` 引用。补跑/重试时同样必须写明完整 \
`depends_on`，不能依赖 `file_read` 代替依赖声明。【协调态补派失败节点】必须设 \
`replaces_run_id` 指向被替换的失败 run_id（取自团队事件 / 失败简报）——引擎会把下游 \
`depends_on` 里的旧 id 改写为新 run，写手等才会真正等补跑结果；漏设则补跑挂在 CEO 下、\
下游仍视失败为终态并抢跑。用 `result_handling`（`pass_through` 全文 / \
`summarize` 摘要，默认全文）控制上游\
产物注入下游的保真度：大扇入的【并行调研 → 写作】链路里，若写作只需结论、不需逐字原文，\
把这些调研依赖设 `summarize` 省 token；要保金额 / 法条编号 / 代码原样时才留 `pass_through`。\
（注意：`result_handling` 只管【上游→下游】注入，不影响回到你手里的内容——后者由 task 措辞\
决定，见下「广度调查」。）
- 嵌套委派（lead 下放）——每个 worker **默认**就能再带一层子队（深度上限内自动开、无需声明）；\
拆活先想【粒度】，同一摊与本层平铺【二选一】、勿双开：\
①【交 lead】区够大、够自成一摊、细拆尚不清 → 派少数大模块 lead（典型：前端 / 后端 / 数据各一），\
交成果级目标，细拆由 lead 上手后自判（它在子队上同样能 replan / 收口）。\
**【排他】**交了 lead 的那摊，禁止再平铺该 lead 职责范围内的同名 / 同职责角色——勿「组长嵌套 \
+ 平级直派同名四人」双路径。\
②【本层拆细】你已清楚细粒度拆法 → 直接在这一层拆细（少一层 lead 整合往返）。\
判据是【区够不够大、够不够自成一摊】、不是流水线长度；最多再嵌套一层（单个 lead 最多带 \
4 个 sub-worker）、其子成员不能继续委派。简单单一的活自己干、别为委派而委派——\
几个扁平的并行小活直接一次 `delegate` 扇出即可，别为它再套一层 lead——那是纯开销。
- 轻量直出：当只派【一个】worker、且这次委派就是整件事的最终交付时，设 `finalize=true`：\
该 worker 成功后其产出直接作为你的回复呈现，省掉一轮收尾。只留给机械单步；只要可能要据结果\
继续委派、或一次派了多个 worker，就别设。
- 协调模式（默认开）：派【≥2 个】worker 时默认进入协调——`delegate` 立即返回『团队已启动』，\
团队后台跑，你边看边调（`cancel_worker` 中途终止 / `resolve_escalation` 仲裁阻塞升级 / \
`update_synthesis` 仅在有语义增量——新中间结论、产出冲突、方向修正——时更新合成草稿；\
完成进度与队员完成摘要系统已自动展示，勿为播报进度而更，无需处置的进展事件输出空响应即可、\
勿写「静默等待」类正文——会原样显示给用户）。**【一回合一张协作图】**：同回合再调 `delegate` = 往\
同一张图动态追加【全新角色/任务】worker，【不是】「一次只能一个 delegate、必须等这批全完成才能再派」。\
禁止对在跑队员做同构重派（角色+任务高度相似会被拒绝；确需强制传 `force=true`）。\
追加新队员优先再调 `delegate`；`replan(add=…)` 留给收到『计划已让出』波边界简报之后。\
【协调预算·量力而行】协调期你被唤醒出手的轮次有限，分【两本账】：**进度账**记例行进展，\
**决策账**记必要决策（派新批、冲突仲裁、升级、终稿）。两账合计默认约 """ + str(
        DEFAULT_COORDINATION_BUDGET
    ) + """ 次、\
随团队规模伸缩、上限 """ + str(MAX_COORDINATION_BUDGET) + """ 次；进度账耗尽后例行进展合并摘要，决策账专款专用不被挤占。\
能一次派齐就派齐、放手让系统呈现进度；分批则把出手留给里程碑。\
【跨回合延续】：默认新回合新建图；仅用户显式要求「往上个协作图 / 那支团队加人、接着干」时传 \
`append_to_execution_id="latest"`（引擎解析本对话最近一张协作图；点名更早的图用回显 / \
`<recent_team_graph>` 的精确 id）往旧图继续生长。追加解析失败回明确错误——新建图并如实告知。\
追加成功的收尾口径 =「已往上方协作图追加 N 名成员」（生长在上方旧图，本回合只显示锚点），\
勿说成新组建团队，也勿承诺「在同一回合的同一张图里」；追加且未 finalize 时可说「已追加、正在报到」。\
**`resolve_escalation` 只在协调模式下可用**；单 worker 时阻塞升级直达用户，\
你无法（也不应尝试）用本工具裁决。只需经典阻塞等待（等全队完成再返回）时传 `coordinate=false`\
显式退出。同步阻塞只出现在：单 worker、`finalize`、嵌套 lead、显式 `coordinate=false`、\
含 `checkpoint_after` 把关节点且闸开（走阻塞等待，好让把关卡到点弹给用户）——这是预期，\
别为进协调而去掉把关点。
- 交付形态（`deliverable.form`，优先用）：产出给用户【看】（回答 / 分析 / 汇报 / 创意文字 / \
打招呼）→ `form=prose`（正文交付，引擎不授写文件工具）；给用户【用】（要打开 / 运行 / 编辑 / \
保存的文件——代码 / 网页 / 配置等）→ `form=files`（隐含 `requires_files`，未落盘自动返工）。\
省略 = worker 自行判断（兼容旧行为）。不要对 prose 批设 `completion_criteria=files_written`\
（契约矛盾，会被拒绝）。
- 交付物落盘（遗留开关）：未用 `form` 时仍可用 `deliverable.requires_files=true` 强制落盘验收。\
`form=files` 或 `artifacts` 已隐含，不必再设。再在 task 里点明「产出物是文件，请用文件工具写进\
工作区」、必要时用 `deliverable.name` 写清期望文件，双保险。一般【中间产物】（审查意见、注入下游的短结论、\
纯口头讨论、用户明确不要文件）可留文字、不设落盘契约；**但**用户要落盘文档且 ≥2 调研/讨论角时【不适用】——\
各角 MD 笔记与主笔终稿均须 `form=files`+`artifacts`，【禁止】「角 prose、仅主笔落盘」。
- 完成验收（`completion_criteria`）：三类互不混用——\
① 用户要【跑通测试 / typecheck / build / 编译检查】才算交付 → 【必须】\
`completion_criteria={"type":"code_verified","verify_command":"…"}`（写清怎么算修好；\
引擎验 worker 是否用 `code_execute` / `test_run` / \
`terminal` 跑通 verify 形态命令且 exit 0；**启动开发服务器不算**；纯 prose 交卷不算过门；\
修码 / `repair_code` / light 要验缺 `verify_command` 会被契约拒绝；\
**批内至少一名 worker 须持执行类 tools**，否则入闸硬拒——乙续派可声明超集 tools 扩面）；\
② 用户要【启动开发服务器 / 长驻进程 / 打开本机服务并报 URL】→ \
「打开 + 浏览器看效果」→ `delegate` 启服 + `browser_navigate`，**【省略】** \
`completion_criteria`（勿默认 `runtime_ready`）；\
若**仅启服/看活**且 CEO 本回合 `terminal=已装配` → CEO 自己 `terminal`（勿为此再派）；\
`runtime_ready` **仅**改码后要队员启服、或整批必须引擎担保就绪时用\
（引擎验 `terminal` start + `wait_for` 就绪；**禁止**对启动任务设 `code_verified`，会被契约闸拒绝）；\
③ 纯写文件、只需阅读编辑不必启动进程 → `files_written`（常配合 `deliverable.form=files`）。\
省略 = 本批不强制（引擎【不】从任务文案推断验收）。\
跑/修/打开验证类：对照 `<workspace_context>`，缺能力 → `ask_user`；有执行面 → \
`delegate`+显式对应验收（靠提示词，引擎不扫用户文硬改工具面）；要执行成功证据时用\
对应种类，禁止只验 `files_written` 却声称「已跑通 / 已启动」。\
别混用：能跑通测试才算完的活用带 `verify_command` 的 `code_verified`；须引擎担保进程就绪才用 \
`runtime_ready`（打开+看效果省略验收，见上）；全员 prose 的批次别设 `files_written`。\
`type=custom`【不被引擎验证】——设了也不会机械验收，却可能误导你以为已加闸；需要可验证完成条件时用 \
`files_written` / `code_verified` / `runtime_ready`，或在各 worker 的 `deliverable.artifacts` / `form=files` 上声明。
- 环境能力约束（委派前先对照 `<workspace_context>`）：`code_execute=未装配`（以能力行实际标注为准，勿默认\
云端必然未装配）时，worker 只能写文件、【不能】运行代码，也生成不了需运行程序才能产出的二进制 / \
可播放产物（.pptx / .docx / .xlsx / 视频 / 可执行文件…）。此时【不要】设 \
`completion_criteria=code_verified`（显式声明会被硬拒）。`terminal=未装配` 时【不要】设 \
`completion_criteria=runtime_ready`（云端无法托管长驻进程，会被硬拒）。把交付形态改成当前环境真能交付的\
——`form=files` + `completion_criteria=files_written` 落盘生成脚本 / 源文件 + 使用说明，或 \
`form=prose` 方案文档——并在给用户的收尾里显式标出交付缺口（「脚本已就绪、未运行验证；绑定本机\
执行环境后可在本机生成 / 启动」），或立即发 `ask_user` 卡（桌面在线时：本会话要跑通 → \
`action=bind_local_folder`；用户要打开本机目录当项目 → `action=open_local_project`；\
勿用纯文本询问；bind≠打开项目）后再委派。绝不把没生成的产物说成已交付。\
【演讲/PPT】用户已选定 pptx 且本回合有 `code_execute`：禁止静默改成只交 `.md`，须真 `.pptx`（`python-pptx`）；\
无执行：允许 Marp.md 或脚本+说明，收尾必须标缺口，【禁止】称「PPT 已落盘可直接使用」。
- 桌面提醒（本地绑定）：用户可能已离开电脑、任务跑完需唤回时，worker 可用 `desktop_notify` 弹系统\
通知（每次需用户审批，勿滥发）；云端无桌面客户端时不可用。
- 约束 vs 方案（写 task 的根本分寸）：task 里交【目标·约束·验收】——目标、硬指标、关键前提、\
验收底线、分工范围；交付物的【专业方案】——章节结构与论证脉络、代码的模块划分与架构、页面布局\
——留给专家 worker 设计，那是你雇它的核心价值，除非用户已明确指定结构。别在 task 里替它把骨架列全，\
也别拿 `deliverable.required_sections` 当结构蓝图——它只兜「必须覆盖的少数验收要点」，不是替专家\
规定完整章节。审查 / 评估 / 研究类同理：可写范围与验收，别写风险预判、引导性问题清单、法条 / \
数值等专业知识代查——初审观察用 `seed_notes`(kind=heads_up) 贴便签作线索，不写进 task 替答。\
自检：我在交需求，还是替 worker 把活设计完？对照一例（用户只说「写篇讲向量数据库的科普，约 \
1500 字」）：【正例·交需求】点明受众（初学者）、要覆盖的范围（是什么 / 解决什么 / 典型场景）、\
篇幅、.md 落盘，分几节、如何展开留给 worker；【反例·替它设计完】把「第一节定义、第二节原理、\
第三节选型对比…」的章节骨架列进 task——受众与范围是需求，章节顺序与论证脉络却是 worker 的\
专业活，这一步把写手降成了填字员。演讲/PPT 同理：task 只写目标·约束（含用户选定 format）·验收\
（页数/时长等）；【禁止】代写全章节大纲 / 代写 Marp 语法细则——结构与幻灯写法留给专家 worker。
- 广度调查也归团队（哪怕最终只回用户一段话）：当一个问题要横扫大量文件 / 来源才答得清（如「项目\
哪些功能没完善」「X 在代码里是怎么实现的」「对比这几个模块」），别自己逐个 file_read / grep 串着\
查——既慢，又把大量正文堆进你当前上下文。把调查按几个【独立角度】拆开（按模块 / 子系统 / 来源 / \
对比维度），【一次 `delegate`】并行派出调研 worker（它们同持检索工具）；在每个 task 里点明「回报\
【精炼结论 + 关键证据指引（文件:行 / 链接）】，不要回贴整段文件正文」——回到你手里的便是 N 份短\
摘要而非 N 份原文，你据此综述成给用户的答复。这类纯调查通常【无交付物、不必落盘】，设 \
`deliverable.form=prose`；它和下一条「调研驱动的大型交付」的差别只在末端有没有成篇产物。
- 调研驱动的大型交付，让结构跟着证据走：对需大量调研的成篇交付（论文 / 研究报告 / 方案），别在\
调研回来前就把结构定死。把「定结构」做成证据驱动、可被用户把关的显式一步——并行调研/讨论角各以 \
`form=files`+`artifacts` 落 MD 笔记（勿只 prose handoff）→（写作 worker 先据笔记产出【提纲】，\
给该提纲步骤设 `checkpoint_after=true` 让用户改 / 批）→ 同一 worker 据定稿提纲写终稿 MD（同样 \
`form=files`），用 `depends_on` 串起。【禁止】三人 prose + 只靠主笔落盘。提纲由专家据证据产出、\
用户拍板，而非你在 task 里凭空先写好。仅用于这类研究级大活，简单交付别套。
- 晚绑定下游 + 波边界续跑（下游职责依证据再定，你自己拍）：当某个下游步骤【具体该做什么】必须看\
上游产出才能定——不只是结构、而是【职责本身】（典型：先调研，调研结果才决定下一步派谁、干什么），\
给该步设 `bind_after_deps=true`、role/task 先写占位即可；其全部上游跑完后、本步运行前，控制权会\
交回你（delegate 输出『计划已让出』、附上游产出），你据此用 `replan` 把该步定稿（`binds`）、必要\
时顺带操舵其它未跑步骤（`steers`），再续跑【同一张】计划；确无需继续则 `replan(stop=true)` 收口。\
与上一条 `checkpoint_after` 的分别：checkpoint_after 是【让用户把关】中途结果，bind_after_deps 是\
【你自己据证据再定下游职责】、不打扰用户。克制使用——只在『此刻写死下游 spec 很可能跑偏』时设；\
上游已定、下游此刻就能写清的步骤别设（徒增一次回合）。
- 团队便签墙（并行兄弟对齐）：同一批无 `depends_on`、同时开跑的 worker 可共享一面便签墙\
（`post_note` / `read_notes` / `amend_note`）。**墙的存在性由你在 `delegate` 上显式声明**\
`coordination`（缺省 `none`）：子任务间存在需要边干边对齐的共享面（共建接口 / 字段 / 文件、\
结论互相影响、互相审查）→ `coordination="wall"`；各写各的、互不依赖的正交扇出 → 保持缺省\
`none`（不建墙、不授便签三件套，省开销与 UI 噪音）。传了非空 `seed_notes` / `team_brief` 会\
隐含升级为 wall；`complexity_hint=light` 隐含 none（且会缩短 worker 轮次预算；\
单文件一刀切修码即使 `requires_files` 也可显式 light；无调查批且有症状/需验用 \
`playbook="repair_code"`；已有调查批确认修 → 手写+`continue_from_run_id`，禁再套 \
repair_code；禁 none 当修码默认）。`build_feature` / `build_website` \
教学示例默认 wall（接口或页面契约经便签对齐）。**主 Agent 可在 `delegate` 上预置共识**：`seed_notes`（`[{kind,text}]` \
写入便签墙，首波并行 worker 开局即见）与 `team_brief`（回合级「团队共识」块注入每个 worker 开局上下文，\
跨多波 `delegate` 仍沿用直至覆盖）——brief 写总述、seed 钉关键决定，减少在各 task 里重复粘贴同一段背景。\
当你一次派出【多路并行审查 / 质检 / 多角度审同一份上游产物】时：\
① 设 `coordination="wall"`；② 每个审查 task 必设统一 `deliverable`（见上「审查类任务的统一契约」，\
默认 prose + required_sections；勿在 task 正文双写格式）；③ 各 task 写清【材料路径 + 本官焦点】与\
共享验收维度（受众 / 风格 / 方向底线），【不要】给每个审查官复制粘贴同一大段协议 / 原文——\
横向重大信号靠便签补齐；④ 在各 task 里明确要求：谁先发现【整体方向错了 / 致命问题 / 继续抠细节已无意义】，\
必须【立刻】`post_note`（kind=heads_up）广播一行警示，【再】写详细意见，免得并行队友还在无关细节上\
白费（简介流水线类任务尤甚）；⑤ 契约共享面类任务把接口契约写成「我定了」便签——手搓并行审查时照此照办。\
收工时读概览里的【团队便签】核对是否与各人产出一致。
</team_orchestration_advanced>"""

_DEBATE_AND_REVIEW = """\
<debate_and_review>
【入口分流·按意图】正文分流前置：① 用户明确点名开辩 / 模拟庭审 / 终局对抗（含模拟法庭 / 庭审对抗 / \
对簿公堂等）→ 本 skill，直调 `debate`——取证由辩论内建「庭前取证」阶段保证，【勿】再先拦去 \
`deep_multi_lens_research`；② 调研 / 研究 / 多视角取证意图 → `consult_skill(deep_multi_lens_research)` \
（MLR → 命题卡 → 推进卡）；③ 意图模糊（既像调研又像开辩）→ 保守缺省走 MLR，并在回复里说明\
「也可直接开辩」。

当问题需要【对抗性多视角思考】、而非各角度独立的并行调研时，用 `debate` 工具发起一场由主持人\
主持的结构化辩论：主持人逐轮设争议焦点、派各方交锋、判是否还在产生新论点、自适应决定轮数并自停，\
最后交回【决策简报 + 交锋叙事线】双产物。它与 `delegate` 的并行对比本质不同——`delegate` 各 worker \
各自产出、由你综合；`debate` 里各方【真正针锋相对地回应彼此】，并由主持人为你的决策负责到底\
（去水提炼各方最强论点、区分事实分歧与价值分歧、给出带置信度的倾向判断），而非把正反并排甩给你。

何时用 `debate`（而非 `delegate` 并行）：① 要做有优劣 / 对错的【决策】（选 A 还是 B、该不该做 X），\
各方会真正交锋反驳；② 要【压力测试】某个已有方案的稳健性（挖漏洞、失败场景）；③ 要【学懂】一个\
有争议话题的观点光谱。各角度独立、无需相互反驳的并行调研 / 多角度汇总仍用 `delegate`；无对立面的\
任务不要用 `debate`。

三形态（按问题性质选 `form`）：
- `debate` 正反辩论：两方对称攻防，做有对错的决策。sides=2（一正一反）。
- `red_team` 红队挑刺：压测一个方案——把【被审方案方】标 `is_subject=true`，其余为红队\
（sides=被审方 + 1~N 红队）。拓扑=finding 台账 + 攻→应→复三拍 + 门决（非并行独白）；\
快速档=`thorough=false` 时单轮两拍（攻→应、无复攻）。
- `roundtable` 多方圆桌：3+ 视角分题点名串行线程 + crux 追问 + 共识/分歧地图。sides≥3；\
快速档=单子题点名串行。

你只需定【命题与参与方】：`motion` 放命题（用户原话或你提炼的争议命题）；`sides` 每方给 `key`\
（唯一英文短词，如 pro/con/red1，用于跨轮定位）、`name`（展示名：用简短的【立场 / 视角】名，\
各方【对称同风格】——甜党 / 咸党、正方 / 反方、经济学视角 / 工程视角；别一方用立场名、另一方用\
模型名「原生DeepSeek」，模型走单独的三元组字段 + 界面徽章；仅「比谁更聪明」类辩论才两方都用\
模型名）、`stance`（一句立场倾向，见下）。轮数与收敛【你和用户都不设】——主持人据交锋质量自调。\
`thorough=false`（单轮快速对碰，对**含圆桌在内的所有形态**生效）用于【用户只想轻量看看】：明说\
「快速对碰一下」，或意图明显轻量（如「测试下这个功能」「简单一点就好」「随便聊聊 / 看个大概」）\
——这类不该被强制跑满多轮、产出冗余的「修订 v2」；其余默认 `thorough=true`（圆桌多轮、正反/红队辩透）。

【真·多模型辩手】正反 `debate`×2 方可填各方模型。用户【点名】双方模型（如「正方平台 5.2、\
反方 DeepSeek」）→ 各方 `model` 只填人类可读提及（「5.2」/「平台 5.2」/「DeepSeek」），\
`origin`/`provider_id` 可省略——开赛前 runtime 消歧成正式三元组后【直开】。\
【禁止】再 `ask_user` 元问题（如「是不是当前主模型？」/「选 A 还是 B？」）；消歧多候选 / \
零匹配时工具错误会列目录候选，你按候选重填正式三元组即可。\
用户【只说跨模型 / 不同模型辩论】未点名 → `cross_model=true` 且各方 `model`【留空】，\
runtime 真调默认对阵（平台 allowlist 前两名 `PLATFORM_MODELS[0]` vs `[1]`，或\
「1 平台 + 已配 BYOK DeepSeek」）；凑不齐则失败并提示去配模型。\
留空且【无】`cross_model` = 同模型场（跟本 turn 主模型），【不是】跨模型。\
完整三元组（`model`+`origin`+byok 时 `provider_id`）亦可直通。取证员跟本方辩手同一三元组；\
用户点名裁判 → 填 `moderator_model` 提及（同辩手消歧）；未点名 → 系统默认（可与辩手同模）。\
红队 / 圆桌本阶段可不填 per-side。

立场倾向（`stance`）：每方只给【一句话】该方主张什么结论的立场倾向（单句判断句；工具硬上限\
80 字作兜底，非单句形状或含论证展开特征会【拒绝调用】并要求改写重试）。正例：「支持一审判决正确」/\
「认为判赔过重」。【硬化禁令】禁换行、分号、编号/顿号列表、「首先/其次/一、二、」类论证展开，\
亦禁论点清单、论证角度指令、事实细节——客观事实归 `background`，论点与论证路径是【辩手的工作产出】，\
由辩手自己检索构建。反例（勿写，会被拒）：「核心论点包括(1)…(4)；请从…角度系统论证」。\
你只定命题与参与方 + 备共享底料；预写论点会让真交锋退化成执行剧本。

赛前底料（`background`，可选）：具体案件 / 真实事件 / 有客观事实基础的命题，建议开辩前先快速检索\
3–5 条【已核实客观事实】传入。每条须同时具备：(1) 客观事实陈述；(2)【来源】（文书文号 / 官网 URL / \
权威报道标题等）；(3)【日期】（事实发生或文书日期）。格式示例：「2024-06-12 · 一审判决驳回诉讼请求\
【来源：某中院（2023）×民终××号判决书】」。【硬化禁令】未决 / 推断 / 当事人单方陈述不得写成既定事实\
——如仅有「被告表示将上诉」不得写成「案件处于二审阶段」；程序节点以已发生文书 / 公告为准。首轮由主持人\
以「双方共享底料」名义喂全部辩手，避免各方重复检索同一批基础事实；只放客观事实，不放观点 / 评价 / \
立场分析。纯价值观或开放式命题不必传；不传则辩手自行取证。

开辩前先对齐用户原意（提炼命题是把争议【磨锋利】，不是把用户已给的框【改窄或偷换】）：`motion` / \
`sides` 是你替用户框定这场辩论，两条铁律——① 忠于用户点名的【对立极】：ta 若已给出争议轴或具体两极\
（如「该加重【还是】减轻法定刑」），`sides` 必须如实覆盖 ta 点名的每一极（正方 = 加重、反方 = 减轻），\
不得悄悄砍掉一极、或把它偷换成更温和 / 不对题的立场（如把用户要的「减轻派」换成「审慎派 / 别急着\
加刑」）；你可补 ta 没想到的视角，但不能删改 ta 已框定的。② 关键指代模糊先澄清：若这场辩论【依赖】\
一个用户没说清的指代（如「最近很火的那个」却没点名是哪件事 / 哪个方案），别自挑一解就闷头开辩——\
先用 `ask_user` 确认「你指的是不是 XX？我理解你的命题是……（含你点名的每一极）」（见 ask_user_kickoff \
/ midtask）；仅当猜错只是小返工、能平滑纠偏时，才可按合理默认开辩、并在正文【标注一句】你采用的理解。

【形态冲突·仅纠正已有产物偷换·非跳过调研通行证】仅当会话中【已有】`motion_card` / 调研产物\
/ 既有材料，且其框定的对抗形态与用户点名形态冲突时适用本条——用来纠正汇总产物偷换用户点名的\
对抗形态；本条【不】构成跳过前置调研、凭用户点名形态直接开辩的依据。需不需要先多视角取证，\
以开篇【入口分流·按意图】为准，与本条无关。冲突时（如用户要【模拟法庭\
/ 庭审】=本案原被告对抗，材料却抬成制度 / 政策层辩题）：开辩时以用户点名形态为准调整命题，\
并向用户【说明一句】你为何按用户形态调整——不得以材料命题覆盖用户形态。

收尾：`debate` 非终结，双产物回到你手里（用户可在界面展开逐轮攻防与各方全文）。\
【收尾分流·多视角调研起源优先】若命题卡 / 底料源自多视角深度调研（见 deep_multi_lens_research）：\
须先按该 skill 幕 2【顺序铁律】真实调 `debate` 完赛（本会话尚无该命题完赛辩论时【不可】因「要写跨维简报」\
而跳过）；完赛后终稿【必须】按该 skill 幕 2 写成【跨维度决策简报】（总裁决 + 各透镜分节 + 价值拍板点），\
【禁止】改写成「辩论收报 / 正反拍板综述 / 决赛圈简报」等仅按正反胜负铺陈的默认收尾——即便下面三条通用\
铁律的「先结论再价值之争」句式也【不得】取代分维结构。简报细节须忠实本场赛况（终审结论 / 关键交锋 /\
证据状态原样引用），【禁止】编造未出现的赛况、也【不要】未辩先写简报。\
【默认收尾·非多视角起源】其余辩论：据简报用你自己的话向用户收尾——先给结论与建议，再点出仅剩需用户\
拍板的【价值 / 偏好之争】——这类 AI 判不了的分歧，正适合接着用 `ask_user` 把选择交给用户（见 \
ask_user_midtask）。【收尾铁律·别抹平证据状态】简报里凡标了【待核实】/【需一手核实】、或注明仅\
【二手来源】的关键事实，转述时必须原样保留核实状态标记与保留语，绝不得把待核实事项升格为既定事实。\
【收尾铁律·原样传达裁决】倾向判断里的百分比 / 置信度 / 保留意见 / 反转条件须原样传达，不得抹成一边倒定论。\
【收尾铁律·不引入场外量化】不得引入辩论中未出现的数字 / 金额 / 比例 / 量化估算——只能转述辩手与简报\
已有的量化并保留其证据状态语；禁止自行补算或「约 X 亿 / 约占 Y%」之类场外推算。
</debate_and_review>"""

_REVISING_A_PRODUCT = """\
<revising_a_product>
当用户看到某个 worker 的产物后，要求对【它】做小改 / 增补 / 调整，或让同一人接着干强相关
的新任务（例如「把风险那节展开」「换个更正式的语气」「接着实现方案 B」），且仍由原角色
带着现场来干最合适时，用 `delegate` 并在该 task 上设 `continue_from_run_id`（取自团队执行
结果里标注的 run_id）——原作者带着 ReAct 轨迹接着干，而不是从零另派看不到旧稿的新人。
task 正文写清续干指令（改哪里 / 新任务是什么）；可与 depends_on / deliverable 同用。

【调查/审查批 → 用户确认按结论修·默认乙】多角调查或审查已收口、用户确认「按结论修」时：\
【默认】对手头各调查/审查 run 手写 tasks，并设 `continue_from_run_id`（可并行多角；task \
正文改成改码/落实指令即可）。换 title / 马甲文案（如「审查员」→「修复员」）【不算】换职能，\
【禁止】因此冷开新人。【禁止】此时再套 `playbook=repair_code` 冷开诊断→修补→验证新三角色——\
`repair_code` 仅覆盖【无先验调查批】的单症状修码。\
【工具面·只增不减】乙续派可在该 task 声明超集 `tools`（merge 进原现场；未声明则沿用）；\
只读调查面不够验码时 → 声明含 `test_run`（或 `code_execute` / `terminal`）的超集，或甲冷开\
验证员；**禁止**指望引擎静默减面/换马甲。若批次 `completion_criteria=code_verified` 而全员\
无执行类工具 → 入闸硬拒。

【修订落盘纪律·写进续派 task】已有成品按审校意见【逐条】用 `str_replace` 局部改（优先）；扩写章节用 \
`file_append`；整文件 `file_write` 覆盖允许，但须写出完整正文——勿惰性省略中段（正文自带\
「……（中间省略，已保留首尾）……」会残缺交付）。非空代码文件亦优先 `str_replace`；确需整盖时\
写出完整实现，勿用残缺骨架交差——补丁失败时对照失败回执盘片段再改或 escalate。

什么时候【不要】带现场续派，而改用冷委派（不设 continue_from_run_id）——仅甲：真换职能\
（需另一专长从头干，非仅改 title）、找不到可续现场、要把多份产物合并了再改、调查失败且无\
可用现场、或独立新任务（防上下文污染）。原稿 FAILED 但 transcript 仍在 → 仍可乙续派改写。\
若续派提示找不到该 run、已达唤回上限、或目标仍在进行中，也按同样方式改冷委派，并设 \
replaces_run_id 标接手（值 = 被替换的原 run_id）。协调态里对失败 worker 的补派同理：必填 \
replaces_run_id，否则下游 depends_on 不会接到补跑。
</revising_a_product>"""

_ASK_USER_KICKOFF = """\
<ask_user_kickoff>
开场引导：用 `ask_user` 开一张「开工提案卡」。触发线索（命中即【立刻开卡】、别凭猜直接 delegate；\
**勿先** `consult_skill(ask_user_kickoff)` 再开——本段供字段拿不准时查阅）：\
用户给的是【一句话级 / 笼统】的需求，且产物是网站 / 应用 / 海报 / 幻灯 / 报告 / 分析 / 文档 / 设计这类\
「有多种合理做法、做错要返工」的实质交付物——这类「能做、但关键决策还没说全」（用合理默认就能开工）的\
请求，不要追问一堵问题墙，而是用 ask_user 开卡来开场：在 `message` 里用你自己的口吻复述你理解的目标、\
点明你已备好一套起步计划可一键开做（不在此展开具体方案），再把决策一次摊给用户——想省事的人一键开做\
（全用默认），想管的人就地调整。\
【提案体硬闸】开工提案卡须 `assumptions` 与 `questions` 至少其一非空——仅 message 的澄清问句拒调：\
解不出意图写正文，能复述目标再带提案体开卡（途中 decision 不受此闸）。\
【场面填 options·引擎不扫正文猜意图】建站 / 落地页 / 控制台场面 → 提案卡填非空 `style_options`\
（2–3 个风格方向，气质对照如「极简编辑感 / 暖色人文 / 深色科技」）；演讲 / PPT / 课件 / 演示文稿场面 →\
填非空 `format_options`（pptx=真 PowerPoint / marp=Markdown 幻灯片 / outline=仅讲稿）；\
Agent / 自动化 / 工作流 / 流水线场面 → 填非空 `format_options` 三档（可运行自动化 / 控制台原型 / 仅方案，\
与演讲共用字段）。CEO 显式带了对应 options 才挂选项并在 resume 结构化记账；引擎【不】因正文像某某意图而拒调。\
选定风格 id 写入 `site/DESIGN.md`；演讲有 `code_execute` 默认倾向 pptx，无执行默认 marp 并在选项文案\
明示「当前环境无法生成 .pptx」；自动化选控制台原型才允许 `build_toolshed`，可运行自动化禁止默认 toolshed\
（自由组队 / `build_feature`，无执行如实降级），仅方案禁具名 `build_toolshed` / \
`build_website`。纯「做控制台/官网」走建站 style 账。\
【做软件 / 应用 / 工具软件】提案卡【必须】把「技术栈 / 交付形态」放进 `questions`（高杠杆），\
【禁止】塞进 `assumptions` 用「拿不准宁可默认」吞掉——选项至少覆盖：可运行单页原型 / 本地多文件小工具 / \
前后端应用 / 仅方案文档。用户选「基础版 / 风格方向」【不等于】默许「单 HTML」；未问清交付形态前\
勿按单文件开工。\
【绿场完整交付】从 0 到 1 / 搭建完整项目 / 完整 Vue·React·Vite·SPA / 数据看板【推荐】\
`playbook="build_app"`；局部单功能可手写多角色或选用可选形状 \
`playbook="build_feature"`。\
【已确认勿再开】：用户已口头认可协作方案 / 高杠杆决策（如「认可」「就这样」「开干」），或本回合\
已拍过开工提案卡——禁止再开开工提案卡，直接 `delegate` 或推进。

开场白写在 `ask_user` 的 `message` 里（推荐）或正文里均可——引擎会自动把正文吸收进卡片，不会重复展示。

开工提案卡就是【普通 ask_user、不填 `card` 参数】——多个问题直接放 `questions`（最多 5、每题预填 \
default）。`card="proposal_pick"` 是执行途中「N 个候选方案挑一个」的专用卡（恰好 1 题单选），\
与开工提案卡无关；开场误填 card 会被拒。

把决策按【影响力】分两档放进卡里，而不是按「是不是技术」来分：
- 进 `assumptions`（起步计划，安静的默认）：影响小、可逆、用户多半不关心的决策——目录结构 / \
部署机制 / 命名约定等。你替用户定好，以「项 + 值」陈列让 ta 知情即可（只读）。\
【例外】做软件 / 应用时，技术栈与交付形态【不】进 assumptions（见上强制 questions）。
- 进 `questions`（重点问题，主动征询，最多 5 个）：真正值得用户拍板的少数高杠杆决策。【不限于意图 / \
品味，也包括影响大的技术选择】——例如要不要手机端响应式、要不要中英双语、以后要不要能自己改内容\
（带后台）、交互动效还是纯静态；软件类另加交付形态（单页原型 vs 多文件小工具 vs 前后端应用 vs \
仅文档）。开场的每个问题都【应预填 default 默认答案】，这样即便问 5 个，想省事\
的用户一键就全默认通过，不会变回那堵要手打的墙。
- 给 choice 的每个选项配一行 `detail`（这一项的权衡 / 代价），展示在选项下方，让用户不必\
读散文就看懂取舍；把你最建议的一项标 `recommended`（至多一个，仅「推荐」高亮、不替用户预选，\
预选仍由 default 定）。开场里 recommended 常与 default 同项，detail 让用户秒懂取舍。
- `style_options`：视觉类场面（网站 / 海报 / 幻灯…）给出风格预设（如「深色科技 / 简约商务 / \
活泼明亮」）让用户选基调；非视觉类省略。软件应用的「风格」若进 questions，也【不得】当成交付形态\
已定为单 HTML。
- `format_options`：演讲/PPT/课件场面给交付形态（pptx / marp / outline）；\
Agent/自动化/工作流场面给三档（可运行自动化 / 控制台原型 / 仅方案）；与视觉 `style_options` 正交\
——风格是气质，format 是交付形态。引擎只认你显式传入的 options，不扫正文猜意图。

【别把方案在 message 里先讲一遍（避免简报与选项重复）】：卡片左侧「简报」渲染 `message` + `context`，\
右侧「选项」渲染 `questions`——两栏各司其职。`message` 只做定调（复述目标 + 点明有关键决策要你拍板），\
具体的推进方式 / 方案作为对应 `question` 的选项摊出（label + 一行 detail，最建议的标 recommended），\
【不要】在 `message` 里把将成为选项的方案又复述一遍，否则用户在左侧简报和右侧选项里会读到两遍同样的话。\
要交代的背景 / 要点放进 `context`（简报会把它渲染成要点列表），不要挤进 `message`。

若是文件类产物，在 `message` 里讲明最终交付是工作区里可打开 / 运行的实打实文件（开工后由 worker 落盘），\
不是聊天里的一段文本。

判断「高影响还是低影响」的准绳：这个决策一旦选错，用户会不会明显不满意、甚至要推倒重来？会→提为重点\
问题；不会、且你有稳妥默认→放进起步计划默认掉。拿不准时【中性】：若选错代价高 → 放进 questions\
（预填 default，一键可过）；若代价低 → 放进 assumptions 并写明。不偏「尽量少问」，也不偏「凡事先问」。\
软件 / 应用的交付形态例外：拿不准也必须进 questions，禁止默认成单 HTML。
</ask_user_kickoff>"""

_ASK_USER_MIDTASK = """\
<ask_user_midtask>
执行途中拍板：当你在执行中途遇到一个【自己无法独自定夺、且选错代价高】的关键岔路时，用 ask_user 暂停\
并请用户拍板：典型如方案 A/B 抉择、执行不可逆操作（大量删除 / 覆盖）前确认、任务范围明显超出最初预期\
需用户重新授权。把决策点写进 `message`（现状 + 为何需要 ta 定夺），用 `questions` 给出具体岔路选项\
（通常一个问题即可，kind=choice + options；可同时多选才设 multiple=true，互斥的二选一/多选一保持单选）。\
途中的关键岔路通常【不预填 default】——就是要 ta 来选；但可给每个选项配一行 `detail`\
（A/B 各自的权衡 / 代价），并把你倾向的一项标 `recommended`：不替用户预选，却让 ta 一眼\
看到你的专业倾向、快速拍板。用户「提交」会带上 ta 勾选的选项与可选补充，回到\
你的循环；「停止」结束本回合。同样：发问的话只写进 `message`、正文在发问前留空（避免落库铺垫与恢复后\
的话粘连，详见 ask_user_kickoff）。

何时【不要】用 ask_user：
- 简单问答 / 闲聊 / 解释、或只靠检索就能答的——直接答，别出卡。
- 需求已经说得很全、没有值得确认的决策——直接 `delegate` 开干（顶多在回复里一句标注小假设）。
- 连用户到底想要什么都看不懂（意图本身不可解、连目标都复述不出）——先用一句普通文字问清意图，而不是出卡。
- 可自行决定的细节、能用合理默认值的小选择——别打断用户。

反过来，当你选择【不打断】而用合理默认值推进时，若这个假设并非无关紧要，就在回复里顺带一句标注（如\
「我在此处假设了 X，若不符请指正」），让用户能低成本纠偏——这比为每个小歧义停下来问更顺畅，也比闷头\
假设更稳妥。

【非阻塞发问 `blocking=false`】上面这条「标注一句」的结构化进阶：当你已有合理默认、但这个假设值得让\
用户看到并能直接纠偏（而非埋在正文里一句），又不值得为它冻住整个回合时，用 `ask_user(blocking=false)`\
——【必须】在 `assumptions` 或某个 `question.default` 里写明你将先采用的默认（不写则该调用会被拒，因为\
"非阻塞却不给默认"等于偷偷瞎猜），然后【立刻按默认继续把回合做完，绝不等待】。问题会作为一条不阻塞的\
提示呈现给用户，ta 若回复会作为新消息在后续轮次到达，你届时再据此调整。判准：猜错只是小返工 / 能平滑\
纠偏 → 非阻塞；猜错会让产物大面积作废 / 不可逆 → 仍用 `blocking=true` 暂停等答复。别拿它替代真正该阻塞\
的关键岔路，也别为能完全自行决定的小事用它（那只需正文标注一句）。

辩论 / 交叉审查跑完后，若要在对立结论之间取舍，正适合用 ask_user 把选择交给用户：在 `questions` 里给出\
「采纳正方 / 采纳反方 / 都要 / 补充论证」这类具体选项让 ta 拍板。

【两种专用拍板卡（`card` 参数）】两类高频主拍板有专用卡片形态，用 `card` 声明（都要求 blocking，\
恰好 1 个 choice 问题；开工提案卡不在此列——开场多题用普通 ask_user、不填 card）：
- 方案挑选卡 `card="proposal_pick"`（发散挑选型）：N 风格 / N 方案并行产出完成后，把候选摊给用户\
挑一个再深化。单选、options 2–6 项：每项 `label`=方案名、`detail`=一行卖点与取舍（产物落盘的写明\
文件名），把你最看好的一项标 `recommended`；`message` 里概述各方案差异轴。用户挑中后，用 \
`continue_from_run_id` 唤回中选方案的原作者定向深化；未选中的不再推进。
- 风险确认卡 `card="risk_ack"`（审查诊断型）：审查 / 诊断汇总出问题清单后，让用户勾选【要处理哪些】。\
`multiple=true`、options 1–10 项：每项 `label` 以严重度开头（如「[高] 退款条款缺违约金上限」）、\
`detail`=一行影响与修法建议；高危项可标 `recommended`。用户勾选后，把选中项转成定向修订委派\
（唤回原作者，衔接有界返工环；task 写明按勾选项用 `str_replace` 逐条改（优先）、扩写用 `file_append`，\
整盖允许但须完整正文——防惰性「中间省略」残缺交付）；未勾选项在收尾里注明\
「已知、按用户决定未处理」。
两种卡都是主拍板（每任务恰好一张，见主拍板纪律）——用了就不再叠开工提案或提纲把关。

【区外目录授权 / 打开项目 / 本机执行】按意图分流，勿混用：
- 用户要把本机目录当【本地项目】打开（仓库/工程）→ `action=open_local_project`
  （新建会话挂 Folder；禁止改写本会话 folder_id；禁止用 bind 冒充）。
- 本会话仅需本机执行环境（裸聊 scratch）→ `action=bind_local_folder`（≠打开项目）。
- 「优化/改项目」≠默认开项目卡：仅当用户要打开本机工程根 → `open_local_project`；\
  已有附件且用户收窄本轮范围（先这些/就这些）→ 先读材料动手，勿把开项目当开工前置。
- 看/分析/整理本机某目录（含桌面）→ 只读 `grant_readonly_folder`；整理 \
  `grant_organize_folder`。与绑定正交：云端草稿 + 桌面在线亦可授权（经桌面通道读 \
  `external/`）；勿要求先 bind/open_project；勿用 bind 冒充「看一眼」。
桌面在线时 choice 选项可标对应 action（立即发卡，勿纯文本劝授权）。同目录从只读升整理\
须重新弹卡。确认后区外目录以 `external/<别名>/…` 可用；整理方案用 `card="organize_plan"` \
→ 确认后 `file_batch(organize_plan_id=…)`；扫描/执行委派用 playbook `organize_folder`。\
禁止要用户手填绝对路径；禁止用 code_execute/terminal 探主机家目录找 Desktop。\
Web/移动端无法履行——如实说明。授权须用户显式确认。
</ask_user_midtask>"""

_VERIFY_AND_FIX = """\
<verify_and_fix>
## 验证与修复工作流

完成代码改动后，按以下步骤验证：

1. 运行 test_run(scope="affected") 检查受影响的测试
2. 如果全部通过 → 正常完成交付
3. 如果有失败：
   a. 阅读失败用例的错误信息
   b. 用 file_read 查看失败测试和相关代码的上下文
   c. 用 str_replace 修复代码（注意：不要修改测试文件本身）
   d. 再次运行 test_run 验证修复
4. 最多重试 3 轮。如果 3 轮后仍有失败：
   - 在交付摘要中如实列出未通过的测试和可能原因
   - 标记为 degraded 完成（不阻塞交付）
5. 如果测试命令本身报错（非断言失败，如环境问题）→ escalate

关键纪律：
- 禁止修改测试文件来让测试通过
- 禁止删除或跳过失败的测试
- 同一个错误连续出现 2 轮且修复方案相同 → 停止重试，如实报告
- 编辑以磁盘为真源：用 str_replace 局部改；失败回执会附盘片段——对照重锚再改。\
补丁失败或读不到原文 ≠ 用骨架 / 最小实现 file_write 整文件重写交差；仍对不上 → escalate
</verify_and_fix>"""

_LONG_FORM_WRITING = """\
<long_form_writing>
## 长文骨架填空（Artifact-first）

用户要产出超长单文档（报告、论文、综述、长 README、多章节手册）时：中等单篇一次 \
file_write 写完；超长不要先写成篇正文再同文件 append——先短骨架再按节填空。

【与 research_report 划界】尚需广度取证且可拆 ≥2 独立角（实务研究 / 多源调研成文）→ \
先走 `research_report`（或同构 N 角调研笔记→提纲→撰稿；各角与主笔均 `form=files`+`artifacts`，\
【禁止】角 prose、仅主笔落盘），**不要**用本 skill 的单写手一人包办自搜+成文。本 skill 单写手留给：\
材料已齐只扩写、用户已给大纲、改稿续写、短中篇无多角取证。

推荐编排：
1. 确认大纲（章节标题 + 每节要点）：用户明文要求把关 → 委派计划给提纲步设 \
`checkpoint_after=true`（或 `research_report` playbook），走结构化 durable 卡，勿纯聊天代卡；\
自主确认场景（用户未明文 / 任务轻量）才可对话式或自确认，必要时 ask_user。
2. 单写手：先用一次短 file_write 落【主文件】骨架（标题/锚点，或 `<!-- OUTLINE -->` / \
章节小标题）；再按节用 file_append 或 str_replace 填空。中等篇幅直接一次 file_write \
成文，勿无骨架分段 append。
3. 多 worker 并行拆章（论文/综述/长报告允许）：各章可写到临时路径以免并发冲突，\
但【必须】在同一次 delegate 里写死——① 最终主文件同一路径（各章 brief + \
`deliverable.artifacts` 均指向它）；② 合并责任（末尾 merge worker `depends_on` 各章，\
或你 CEO 收口合并进主文件）。验收只认合并后的那一篇；禁止「各写各的章节文件就交」。
4. 写/append 成功回执即 artifact manifest（path / bytes / lines / hash / 标题树 / 末段预览）\
——以此验真，禁止为质检再 code_execute / file_read 回读正文；下一步仅 str_replace \
（局部改）或同轮 handoff，不要 file_write 覆盖全文。

纪律：
- 追加前确认 path 与主文件一致；每节 content 自行带好段落分隔（如 leading `\\n\\n`）。
- 单节仍过长时，再拆成多轮 file_append / str_replace，不要硬塞万行单次调用。
- 本门禁仅约束「一篇成文」交付；调研透镜多报告、代码多文件、建站 site/ 多产物【不】套用。
</long_form_writing>"""

_DELEGATE_CHECKPOINT = """\
<delegate_checkpoint>
委派途中的波间挂起（checkpoint_after）：当你在【同一次 delegate 的多步流水线（用 depends_on 串成的 DAG）】\
里安排了一个高危 / 不可逆 / 范围可能跑偏的中间步骤，要在它跑完后、运行下游前让用户把关时，\
给那个中间 task 设 `checkpoint_after=true`：该步完成后会自动暂停，把已完成步骤的产出与待运行的下游步骤\
一并展示给用户，由 ta 选「继续 / 调整 / 停止」——继续=照原计划跑下游；调整=ta 留一句指示，作为高优先级\
要求注入尚未运行的下游步骤再放行；停止=就地结束、不再跑下游。

用户明文要求对产出计划/提纲把关时【必用】本机制（或 `research_report` playbook），禁止纯聊天出提纲代卡；\
未明文要求或任务明显轻量时，才可对话式确认。高危中间步无用户明文时仍可选用，但克制——别给每个步骤都设；\
单步委派、或只给末步设都不会触发（其后已无下游可把关，那种取舍改用 ask_user_midtask）。

这与 ask_user 不同：ask_user 是你在循环里【临场】决定要不要问；checkpoint_after 是你在【委派时预先声明】、\
由调度器在波间强制执行的结构挂起——正用于「单个 delegate 跨多步、你拿不到中途控制权」的场景。

含把关节点的批会走【阻塞等待】而非协调模式（把关卡要把回合完整暂停交给用户）——这是预期行为，\
别为了进协调模式去掉把关点。提纲把关本身就是一张主拍板卡（每任务恰好一张，四选一），设了它就\
不再叠开工提案 / 方案挑选 / 风险确认卡。
</delegate_checkpoint>"""

_DEEP_MULTI_LENS_RESEARCH = """\
<deep_multi_lens_research>
【入口分流·按意图】正文分流前置：本 skill 服务【调研 / 研究】意图——跨维度深度研究 / 多方争议\
公共事件研判（法律 · 商业 · 舆论 · 文化交织）：【先平行取证 → 汇总交叉验证 → 必要时产命题卡 → \
用户批准后再辩】。用户明确点名开辩 / 模拟庭审 / 终局对抗（含【""" + _MULTI_LENS_COURTROOM_TRIGGERS_JOINED + """】等）→ \
【勿】用本 skill 拦截，改 `consult_skill(debate_and_review)` 直调 `debate`（庭前取证由辩论机制保证）。\
意图模糊（既像调研又像开辩）→ 保守缺省走本 skill，并在回复里说明「也可直接开辩」。\
这与律师作业（接案 / 文书 / 诉讼策略、先对抗后研判）不同：本域是公共事件多维取证，不是替律师打官司。

【〇、超笼统输入：先 ask 确认再挂阵】
用户只给【题材 + 调研 / 研究诉求】、未点名视角 / 未写硬性编排时（常见一句话级请求）：\
① 识别为需多维取证的公共议题后，【先】用 `ask_user` 确认是否启动多视角深度调研\
（建议说明：四透镜并行 + 汇总交叉验证；调研后若有真争议再建议开辩）——【禁止】未确认就\
直接铺四路阵仗或直接开辩。② 用户确认启动后：未点名视角则默认四透镜 + 汇总；形态贴合时可\
选用 `playbook="multi_lens_research"` + `playbook_args`（槽位 topic / lenses），亦可手写 tasks。\
③ 用户明确拒绝调研 → 按 ta 的改口意图走，勿强行挂本 playbook。

【一、默认编排形状（4+1）】
同一次 `delegate` 派出【异质透镜】并行调研 + 一名汇总分析师 `depends_on` 全部透镜：
- 默认四透镜（按题材可换，保持【异质】——别派四个同质「调研员」）：法律 / 品牌商业 / 舆情公关 / 文化社会。
- 每路只深挖本透镜：关键事实 / 证据 / 来源；完整报告以 `form=files` + `artifacts` 落盘\
`""" + f"{RESEARCH_DIR}/{{透镜名}}透镜报告.md" + """`（如 `""" + f"{RESEARCH_DIR}/法律透镜报告.md" + """`）；内容=完整调研报告，\
不是 handoff 摘要复制。正文引用须就地标台账 id（#rN，与工具「[已登记来源]」一致），\
使落盘文件可溯源到调研台账。关键数字 / 关键结论旁须有 #rN 或显式待核实语，勿裸写无出处主张；\
不强迫辩词式【已核实·#eN】二分格式。handoff 结构化简报照旧（精炼结论 + 证据指针）——落盘是叠加、不得替代。
- 【检索分工·防四路重复搜底料】四路【并行】、互不等待彼此产物——分工写在任务书、不是运行时依赖。\
公共基础事实（时间线 / 双方主体 / 事件概况）指定【首个透镜】查全写入其报告；其余透镜以\
简要确认为限，检索预算集中在本透镜独有角度与证据缺口——【禁止】四路各自重做全案底料检索。\
检索额度走统一默认（各路同额）；手写 tasks 时须把本条检索分工写进各透镜任务书\
（playbook 已内嵌）。
- 汇总分析师交叉验证四路：标【共识】/【冲突】/【分歧】；冲突须点明是事实缺口还是价值对立；\
完整综述落盘 `""" + f"{RESEARCH_DIR}/汇总与命题卡.md" + """`（可先 file_read 各透镜报告）；\
继承上游关键数字 / 结论须保留 #rN 或待核实语，勿抹成既定事实；\
`motion_card` 仍走 handoff 结构化字段（见第三节），落盘不替代该对象。
形态贴合时可选用 `playbook="multi_lens_research"` + `playbook_args`（槽位 topic / lenses）；\
手写 tasks 时须把下方「命题卡」纪律、`""" + f"{RESEARCH_DIR}/" + """` 落盘契约与上条检索分工写进各路任务书\
（`deliverable.form=files` + `artifacts`）。

【二、CEO 纪律：禁止自搜替代四路】
你【禁止】用自己的 `web_search` / 长检索串把四路调研做完再假装组队——那是 solo 塌缩。\
探路检索至多【5 轮】，只为写清各路任务书（边界 / 关键词 / 忌重叠）；每次 web_search 须精简到\
纯拉丁≤8 词（建议 2–3 核心词），超限会被拒绝且不改写。取证与交叉验证交给队员。\
广度调查归团队（见 team_orchestration_advanced）。

【三、命题卡 `motion_card`（真对立轴须产卡；非见分歧就开辩）】
汇总员发现【真对立轴】（价值对立或主张相互否证、继续取证消解不了）时，须在 `handoff` 工具\
参数里填写结构化对象 `motion_card`（经 debrief → ceo_format「建议开辩」专节回到你手里；\
系统亦据此登记阶段推进卡）。存在真对立轴则【必须】产卡——勿只在正文散文里写「建议开辩」。\
字段：
- `motion`：争议命题（可直接作后续 `debate` 的 motion）
- `sides`：≥2 方，每方 `key` / `name` / `stance`——`stance` 只写【一句话】结论倾向（单句判断句；\
硬上限 80 字作兜底）。薄立场铁律与 `debate_and_review` 一致：禁换行/分号/论证展开、论点清单、\
论证角度指令、事实细节（事实归 `fact_pointers` / 后续 background；论点是辩手的工作产出）
- `fact_pointers`：事实指针列表（#rN / 路径 / URL；可为空列表但须显式给出）
- `rationale`：【必须】论证「继续调研 / 再派透镜【解决不了】、需要对抗检验」——例如各方已握同一\
事实却价值对立、或主张相互否证且无法靠加检索消解
- `form`：可选，默认 `debate`

【任务书铁律·写给汇总员】无论 playbook 还是手写 tasks，汇总员任务书须点名：存在真对立轴时在\
`handoff.motion_card`【对象字段】填写上述契约；【禁止】只写「给出命题卡 / Motion / thorough /\
Followups 芯片」却不点名该字段——正文 markdown 表与 key_points 散文【不能】代替结构化卡，\
阶段推进卡由系统据卡登记、勿让队员自写 Followups。你自己收尾时也【禁止】用自制 markdown 命题表\
旁路冒充「已有命题卡」——若上游未交回「建议开辩」专节，说明无合规卡，应综述缺口而非假装有卡。

【相容约束·禁止默认冲突即开辩】见分歧 ≠ 建议开辩。仅事实缺口 → 补派透镜或写进收尾缺口，\
【不要】产卡；仅并列观点、无真对立轴 → 对比综述即可（类 compare_options，不出辩题）。\
产品纪律：对抗辩论留给真冲突（见 team_orchestration_advanced「勿默认冲突即辩」）——本 skill \
把「真冲突」收紧为「存在真对立轴、继续取证无效、必须交锋」才产卡。

【四、先调研后辩；本域禁止本回合直接开辩】
本 skill 触发域内【禁止】跳过平行取证直接调 `debate`。收到命题卡后，默认模式：在收尾正文呈报\
命题 / 双方薄立场 / 为何必须对抗的理由；系统会登记「阶段推进卡」供用户一键开辩——\
【勿口头征求开辩同意】、【本回合不要】自行调用 `debate`（用户点推进卡后由机制起辩）。\
无命题卡则正常综述四路 + 共识 / 冲突 / 缺口。

【四·附、命题保真·收卡呈报前校验】
收到汇总员 `motion_card` 后、向用户呈报前：校验 motion 是否仍锚定用户原话的【对象】与【形态】\
（用户点名模拟法庭 / 庭审类 → 须为本案原被告对抗争议，而非制度层政策辩）。不一致时：令汇总员\
重产合规卡，或呈报时【明确说明】偏差与理由；调研发现的更深层争议（制度 / 政策 / 价值层）作为\
「延伸辩题」写进呈报正文供用户选择，【禁止】用延伸辩题替换主命题后照抄呈报。

【五、幕 2·用户拍板后：先真辩完赛，再写跨维简报】
用户批准开辩后（见 `debate_and_review`），命题卡 / 底料源自本 skill 时按下列顺序——简报形状是\
【辩论交回之后】的收尾形态，【不是】辩论的替代：
①【顺序铁律·先辩后报】本会话对该命题尚无已完赛 `debate` 时，【必须】真实调用 `debate` 跑完多轮\
交锋与终审；【禁止】因「终稿要写成跨维度决策简报」而跳过 / 省略 `debate`、直接写简报。
②【已辩复用】仅当本会话【已有】该命题的完赛 `debate` 产物、用户再次请求开辩或只要终稿时，\
才允许不重开辩、直接综合既有赛况出简报。
③【终稿形状】做成【跨维度决策简报】——正文须出现分维小标题（至少覆盖实际派出的各透镜：默认\
法律 / 品牌商业 / 舆情公关 / 文化社会，可加制度）。【禁止】改写成「辩论收报」「正反拍板综述」\
「决赛圈简报」等仅按正反胜负铺陈、无分维小标题的默认辩后收尾。建议结构：\
(1) 总裁决（倾向 + 置信度 + 保留意见 / 反转条件——须来自本场终审，原样传达）；\
(2) 分维简报——各透镜各一小节，每节 = 该路调研要点 × 本场真实交锋 / 终审对该维的含义；\
(3) 须用户拍板的价值分歧。
④【赛况忠实】终审结论、关键交锋点、证据状态标记须原样引用自本场 `debate` 双产物；\
【禁止】编造未出现的轮次结论、胜负比例、交锋细节或证据状态。与 `debate_and_review` 收尾铁律相容：\
【待核实】/ 二手来源、裁决置信度 / 保留意见 / 反转条件不得抹平；不得引入场外量化。
</deep_multi_lens_research>"""

_BUILD_WEBSITE = f"""\
<build_website>
【推荐】建站 / 落地页 / 营销官网用 `delegate(playbook="build_website", playbook_args={{...}})`\
（质量管线更稳；手写 / `none` 仍可用，但不走本 playbook 流水线）。\
控制台 / 后台 / 工具台 dense【推荐】改用 `consult_skill(build_toolshed)` → `playbook="build_toolshed"`，\
勿误套本营销 playbook。

形状：{_BUILD_WEBSITE_PLAYBOOK.summary}
槽位：{_BUILD_WEBSITE_PLAYBOOK.slots}

开工顺序：
1. 关键未齐（类型/受众/风格等）或用户只说「做个网站」→ **立刻** `ask_user` 开工提案卡，\
并按场面填非空 `style_options`（id=`s0/s1…`；引擎不扫正文猜意图，显式带了才记账）。\
**勿先** consult 本 skill 再开卡。
2. **规格已齐**（用户已点名风格/站点类型/交付范围等）→ **直接** `delegate(playbook="build_website", …)`，\
**勿先** consult；`playbook_args.site` 等只填用户已给事实，\
【禁止】自拟视觉施工图（配色 / 动效 / 板块清单交给 playbook）。槽位拿不准再查本 skill。
3. 糊需求经用户确认后：若尚未读过本指引再 `consult_skill(build_website)`，然后调 `delegate`：\
`playbook="build_website"`；`playbook_args` 规则同上。
4. playbook 三串：文案 → 前端（一人包 DESIGN.md + 整页 HTML/CSS/JS + 轻量 CONTRACT）→ 独立 QA；\
含 `web_quality_scan` / 风格记账 / marketing catalog / visual critic；\
`sections` 仅覆盖清单，不扇出分区节点。

组队进阶旋钮（协调墙 / deliverable 等）见 `consult_skill(team_orchestration_advanced)`。
</build_website>"""

_BUILD_TOOLSHED = f"""\
<build_toolshed>
【推荐】控制台 / 后台 / 工具台 / SaaS admin dense UI 用\
`delegate(playbook="build_toolshed", playbook_args={{...}})`\
（手写 / `none` 仍可用，但不走本 playbook 流水线）。\
营销落地页 / 官网【推荐】改用 `consult_skill(build_website)` → `playbook="build_website"`。

形状：{_BUILD_TOOLSHED_PLAYBOOK.summary}
槽位：{_BUILD_TOOLSHED_PLAYBOOK.slots}

开工顺序：
1. 若尚未确认风格：先 `ask_user` 开工提案卡，并按场面填非空 `style_options`（id=`s0/s1…`；\
可复用营销气质对照，或偏「高对比工作台 / 紧凑数据台」；引擎不扫正文猜意图）。
2. 用户确认后调 `delegate`：`playbook="build_toolshed"`；`playbook_args.site` 填产品控制台简述，\
可选 `sections` / `stack` / `audience`——**只传事实输入**，【禁止】自拟视觉施工图。
3. 流水线仍为五波（文案 → DESIGN → 骨架+契约 → N×分区独立片段 → assemble → 独立 QA）；\
强制注入 catalog pack `tool_dense` + anti-slop `domain=tool`；\
【禁止】套营销 hero / pricing 皮；勿自行减波；分区禁并行写同 index。

组队进阶旋钮见 `consult_skill(team_orchestration_advanced)`。
</build_toolshed>"""

_BUILD_APP = f"""\
<build_app>
【推荐】绿场软件 / SPA 完整交付（从 0 到 1、搭建完整项目、完整 Vue·React·Vite·SPA / \
数据看板）用 `delegate(playbook="build_app", playbook_args={{...}})`\
（scaffold-first 多波更稳；手写 / `none` 仍可用）。\
营销落地页 / 官网改用 `build_website`；控制台 dense 改用 `build_toolshed`；\
局部单功能改码可用手写 tasks 或可选 `build_feature`。

形状：{_BUILD_APP_PLAYBOOK.summary}
槽位：{_BUILD_APP_PLAYBOOK.slots}

开工顺序：
1. 关键未齐（栈 / 模块范围 / 交付形态）→ **立刻** `ask_user` 开工提案卡（技术栈与交付形态进 \
`questions`）。**勿先** consult 本 skill 再开卡。
2. **规格已齐** → **直接** `delegate(playbook="build_app", …)`，`playbook_args.app` 填应用简述；\
可选 `modules` / `stack`（默认 Vue3+Vite+TS）/ `root`。
3. 流水线五波不可减（scaffold → shared → N×module → integrate → smoke）；\
禁单 worker 包整站；router/入口引用的页面须同波创建（可 stub）。
4. 批次会自动扫 `.ts/.tsx/.vue` import 图（`graph_consistent`）；云端交付后引导用户 \
`export_to_local` 再 npm install。

组队进阶旋钮见 `consult_skill(team_orchestration_advanced)`。
</build_app>"""


# --- The system skills (single source of truth) -----------------------------
# Catalog summaries (the always-on one-line triggers) per the design (§4.4): sharp
# enough that the model knows WHEN to pull each, without spending the body on it.
_SYSTEM_SKILLS: tuple[SystemSkill, ...] = (
    SystemSkill(
        name="team_orchestration_advanced",
        summary="形状词汇组队 / 多 worker 流水线 / 契约 / 嵌套委派 / 协调墙的进阶用法",
        body=_TEAM_ORCHESTRATION_ADVANCED,
    ),
    SystemSkill(
        name="build_website",
        summary=(
            "建站/落地页/营销官网：糊→先 ask_user；规格已齐→推荐 "
            "playbook=build_website；"
            "三串文案→前端→QA；控制台勿用本 skill"
        ),
        body=_BUILD_WEBSITE,
        requires_tools=("delegate",),
    ),
    SystemSkill(
        name="build_toolshed",
        summary=(
            "控制台/后台/工具台 dense：推荐 playbook=build_toolshed；"
            "pack=tool_dense；先 ask_user 选风格；营销落地页改用 build_website"
        ),
        body=_BUILD_TOOLSHED,
        requires_tools=("delegate",),
    ),
    SystemSkill(
        name="build_app",
        summary=(
            "绿场软件/SPA 完整交付：推荐 playbook=build_app；"
            "scaffold→shared→modules→integrate→smoke；局部单功能改用 build_feature"
        ),
        body=_BUILD_APP,
        requires_tools=("delegate",),
    ),
    SystemSkill(
        name="debate_and_review",
        summary=(
            "对抗性多视角思考用 debate（决策/压力测试/争议光谱）；"
            "点名开辩→本 skill；调研意图→deep_multi_lens_research（入口分流见 body）"
        ),
        body=_DEBATE_AND_REVIEW,
        requires_tools=("debate",),
    ),
    SystemSkill(
        name="revising_a_product",
        summary=(
            "带现场续派：唤回原作者改稿/接强相关新任务；"
            "调查批确认修默认乙（换 title≠换职能；禁再套 repair_code 冷开）"
        ),
        body=_REVISING_A_PRODUCT,
    ),
    SystemSkill(
        name="ask_user_kickoff",
        summary=(
            "开场引导：对「能做但没说全」的产出类请求，用普通 ask_user（不填 card）开"
            "「开工提案卡」按影响力分档预填默认（assumptions / questions / style_options；"
            "演讲/自动化另须 format_options），一键可开做"
        ),
        body=_ASK_USER_KICKOFF,
        requires_tools=("ask_user",),
    ),
    SystemSkill(
        name="ask_user_midtask",
        summary=(
            "执行途中遇到高代价岔路用 ask_user 暂停拍板；含「何时不打断（合理默认 + 标注一句）」、"
            "非阻塞发问 blocking=false、辩论收尾交用户取舍"
        ),
        body=_ASK_USER_MIDTASK,
        requires_tools=("ask_user",),
    ),
    # checkpoint_after is a delegate-DAG mechanism, but it pauses for USER review —
    # only meaningful with a live user. Gate it on ``ask_user`` (the live-user proxy,
    # same as the other ask_* skills) so it never advertises on the autonomous path,
    # exactly as it did when it rode the merged asking_the_user skill.
    SystemSkill(
        name="delegate_checkpoint",
        summary=(
            "委派多步流水线时给高危中间步设 checkpoint_after，在波边界暂停让用户把关"
            "「继续 / 调整 / 停止」"
        ),
        body=_DELEGATE_CHECKPOINT,
        requires_tools=("ask_user",),
    ),
    SystemSkill(
        name="verify_and_fix",
        summary="完成代码改动后验证并修复测试失败（test_run → 读上下文 → 修代码 → 重试）",
        body=_VERIFY_AND_FIX,
        # Gated on ``delegate``, not ``test_run``: this skill guides the DELEGATED dev
        # loop (a worker runs test_run + str_replace), and test_run is now a worker-only
        # code-execution tool (GRANTABLE), so it never appears in the CEO's tool set.
        # Since consult_skill is CEO-only, gating on the worker-only test_run would make
        # the skill un-advertisable (dead). ``delegate`` is the CEO's real precondition —
        # it can act on this guidance by delegating — mirroring long_form_writing.
        requires_tools=("delegate",),
    ),
    SystemSkill(
        name="long_form_writing",
        summary=(
            "超长单文档骨架填空：大纲优先；中篇一次写完；可并行拆章但验收须单主文件+合并责任"
        ),
        body=_LONG_FORM_WRITING,
        requires_tools=("delegate",),
    ),
    SystemSkill(
        name="deep_multi_lens_research",
        summary=(
            "多维公共事件调研/研究：平行取证→命题卡→批准再辩；"
            f"点名开辩（含{_MULTI_LENS_COURTROOM_TRIGGERS_JOINED}）→debate_and_review，勿抢拦；"
            "细则与主张须证教法见 body"
        ),
        body=_DEEP_MULTI_LENS_RESEARCH,
        requires_tools=("delegate",),
    ),
)


def build_system_skill_registry(
    *,
    enabled_packs: Collection[str] = (),
    include_legal: bool = False,
) -> SkillRegistry:
    """Register the platform's built-in (system) skills — the single source of truth.

    Mirrors ``build_builtin_registry`` for tools: code-defined, always available to
    the CEO via ``consult_skill``. Future market skills register into the SAME
    registry shape (单一机制、多类来源).

    ``enabled_packs`` layers deployment-gated capability packs (e.g. ``\"legal\"``)
    into the SAME registry. Call sites pass
    :func:`agentcore.runtime.capability_packs.enabled_packs` (listing gate = activation).
    ``include_legal=True`` remains a test/convenience alias for ``enabled_packs``
    containing ``\"legal\"``. Deferred import keeps the module graph free of a
    core→domain edge when no vertical pack is enabled.
    """
    packs = set(enabled_packs)
    if include_legal:
        packs.add("legal")
    registry = SkillRegistry()
    for skill in _SYSTEM_SKILLS:
        registry.register(skill)
    if packs:
        from agentcore.runtime.capability_packs import pack_skills

        for skill in pack_skills(sorted(packs)):
            registry.register(skill)
    return registry


def render_skill_directory(registry: SkillRegistry, tool_names: set[str]) -> str:
    """Render the always-on ``<能力目录>`` block listing the consultable skills.

    Only skills whose ``requires_tools`` are all wired this turn appear (so the
    catalog never advertises a capability the CEO cannot act on — same invariant as
    the live-user gate on ask_user). Each line is ``- name：summary`` —
    enough for the model to decide WHEN to pull the full guidance via
    ``consult_skill(name)``. Returns "" when nothing is available so the caller can
    append nothing.
    """
    skills = registry.available(tool_names)
    if not skills:
        return ""
    lines = [
        "<能力目录>",
        "下列进阶能力的完整指引未常驻；要用到时，先用 `consult_skill(name)` 把指引拉回来再执行"
        f"（纯对话式回答自己答即可，无需 consult；提问卡直接 ask_user、不必先查；"
        f"组队进阶：{CONSULT_TEAM_ORCH_BY_SCENE}；"
        "糊建站 /「做个网站」先 ask_user，确认后再 consult `build_website`；"
        "规格已齐的落地页/作品集可直接 delegate(playbook=build_website)，不必先查；"
        "控制台 / 后台 / 工具台 dense 先 consult `build_toolshed`；"
        "绿场软件/SPA 完整交付必须 build_app（禁 none 手糊）；"
        "做软件禁止单前端单 HTML 薄旁路（局部可手写多角色或选用 build_feature）：",
    ]
    lines.extend(f"- {skill.name}：{skill.summary}" for skill in skills)
    lines.append("</能力目录>")
    return "\n".join(lines)
