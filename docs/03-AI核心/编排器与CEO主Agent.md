---
status: landed
code: apps/server/agentcore/runtime/delegate/
related:
  - docs/03-AI核心/运行时总览.md
  - docs/03-AI核心/执行引擎架构设计.md
skip_if:
  - 只改 WaveScheduler 内核（读执行引擎）
---

# 编排器与 CEO 主 Agent

> **状态**：已确定并落地（CEO 主 Agent + `delegate` 原语 + 协调者工具边界 档2.5：CEO 仅持只读/检索工具，且这些工具只供**侦察/收尾**——生产变更与**成规模的广度调查**都委派）；CEO/worker 的 system prompt 已确立「身份 + 边界」结构，路由**第一拍**定方向（糊需求立刻开工提案卡、勿先 consult；短文未落盘直答 / 落盘派 1 人；该派就派、按活的自然缝拆人），细节（worker 角色模板 / 各 Skill 正文打磨）待迭代
>
> → 见代码：`apps/server/agentcore/runtime/delegate/`（已由单文件拆为包）、`tools/builtin/replan.py`

---

## 核心定位：CEO 主 Agent 模型

编排能力归属于一个**会话型「CEO」主 Agent**——它既是**唯一对话入口与声音**，也是**团队规划大脑**。**身份层级**：用户是老板，CEO 受其雇用、替其掌管这支团队并对其负责，用户才是最终决策者——CEO 关键岔路向用户请示、收尾向用户汇报。CEO 直接与用户对话、可来回澄清；当任务确需团队时，它通过 `delegate` 工具**下达子任务**，驱动执行引擎调度多个 worker 并行/串行工作，并**用自己的声音收尾汇报**（合成器角色并入 CEO）。

CEO 是**管理者**（不是调查员）：它只直接持有「只读 / 检索」工具（联网搜索、读网页、读文件、列目录、grep、**Git 只读** `status`/`diff`/`log`），但这些工具是给它**侦察（开工前轻量探路、判断怎么拆 / 派谁）与收尾（综述团队成果）**用的，**不是让它独自跑完整场调查**。两类活都交给团队：① 会**产出或改动产物**的工作（写 / 改 / 删 / 移文件、**Git 写入**、运行代码）——它本就不持有相应工具，必须 `delegate` 交给 worker，即便只派一个；② **成规模的广度调查**（要横扫大量文件 / 来源、可拆多角度并行）——哪怕只读、哪怕最终只回用户一段话，也应 `delegate` 扇出并行调研 worker，各自检索后回报**精炼结论**，再由 CEO 综述。worker 持有全套工具去动手。

> **底线**：对用户呈现**一个 CEO 声音**；CEO 默认走快的会话档，**轻量 / 单点**的只读对话直接作答（零编排开销）；「组团/下计划/动手产出/广度调查」按需触发。

### 职责边界（CEO）

```
✅ 与用户直接对话、必要时来回澄清（D2）
✅ 轻量 / 单点的只读请求直接作答（一两处文件 / 一条事实就能答；搜索、读少量已知文件、列目录、grep；承袭聊天优先，零编排开销）
✅ 开工前用只读工具轻量探路（判断怎么拆、派谁），团队跑完用自己的声音收尾综述（D3，只写简短概览）
✅ 理解意图、分解任务、决定 worker 数量与角色、分配工具集
✅ 用 delegate 的 depends_on 定义步骤依赖（驱动并行/串行）
❌ 不直接持有生产 / 变更工具（写 / 改 / 删 / 移文件、Git 写入、运行代码）——这类活一律 delegate 给 worker，CEO 不亲自下场堆产出
❌ 不亲自跑成规模的广度调查（逐个 file_read / grep 把整场调查做完）——这类只读但成规模的活也 delegate 给并行调研 worker，CEO 只做开工前探路 + 收尾综述
❌ 重规划只在按需触发时支付，绝不让简单对话背上规划税
```

### 协调者工具边界（档2.5）✅ 已确定

**结构边界（档2，不变）**：CEO 的工具面**只保留只读 / 检索**（`web_search`、`read_url`、`file_read`、`file_list`、`grep`、`git` 只读子集 `status`/`diff`/`log`），**生产 / 变更**（`file_write`、`str_replace`、`file_delete`、`file_move`、`file_copy`、`mkdir`、`file_batch`、`git` 写入子集、`code_execute`）从 CEO 手里拿掉、只交给 worker。`git` 为单工具 + `subcommand` 分派：`schema.approval=NEVER` 使 CEO 注册表自动收录只读子集；CEO 调写入子命令时 `execute` 返回「请 delegate 委派给 Worker」。**路由判据（2.5 细化）**：把「自己做还是交团队」从「**交付物 vs 对话**」重画为「**活的规模与结构**」——见下。

| 切法 | 决策 |
|------|------|
| 分界依据（结构） | 按工具 `approval` 级别：`NEVER`（自动执行、不改环境）= CEO 直接持有；`GRANTABLE`（改动环境、需授权）= 仅 worker 持有。语义自洽，且新增只读工具自动归 CEO、新增变更工具自动留 worker（单一事实源 `build_builtin_registry`） |
| 【直答】（路由） | 单点确认（一两处文件 / 一条事实就能答）、读已知的少量文件、纯问答 / 闲聊 / 解释、**聊天里短文或短改写（未要求存文件）**、以及**开工前的轻量探路**——零团队开销，首字即时 |
| 【委派】（路由） | 凡需 worker 动手的活：① 实质交付物（代码 / 应用 / 网页、脚本、配置、**要求落盘**的成篇文字；哪怕只写一个文件、改一行；task 里点明落盘）；② **成规模的广度调查**（要横扫大量文件 / 来源、可拆多角度并行、需多视角对比 / 辩论、产生大量中间内容）——**哪怕只读、哪怕最终只回一段话**。单 worker 能胜任则 `finalize=true` 直出；形状拿不准才 `consult_skill(team_orchestration_advanced)` |

> **发问优先判据：先判信息够不够、再判规模 ✅ 已落地**：路由第一拍——① 产出类请求若关键高杠杆决策用户没说全，**立刻** `ask_user` 开**开工提案卡**（勿先 consult 再开卡）；② 信息齐了再按「活的规模与结构」判自己做 vs 交团队。**为何前置**：原路由只有「自己做 vs 交团队」一根二元轴，「先问还是先干」不在轴上；提为第一道闸、靠「预填默认=一键通过」避免退回问题墙。详见 §四。→ 见代码: `runtime/resolve/prompt.py`

> **委派判据：活的规模与结构，而非「产出是不是文件」也非「有没有工具」✅ 已落地**：轻量 / 单点的只读请求 CEO 直答；一旦是**有规模或多角度**的活——实质交付物，**或成规模的广度只读调查**——就 `delegate` 交团队，哪怕答复只是一段话。关键转变：判据看**活的形态**，不看**答复形态**。**短文分界**：未要求存文件 → 回复里直写；明确落盘 → 派 1 人。**运行期收敛护栏**：主要靠系统提示词从第 0 轮立框——曾试「累计 N 次只读即软提醒」的代码侧护栏，**A/B 实测被忽略且净负，已移除**；代码侧只保留失控暴走硬兜底（默认关）。配套：CEO 绝不为省委派把整份代码贴进正文；思考里禁止先写完整设计 / 大段代码。→ 见代码: `runtime/resolve/prompt.py`

> **团队形态判据：按活的自然缝拆、能少则少 ✅ 已落地**：上面的委派判据定「要不要委派」；这条定「委派后团队多大」。**① 该派就派**：可分解或质量面敏感 → 派；`finalize=true` 单 worker 留给机械单步或单人落盘短文。**② 按缝拆、不按工种凑**：拆几个看【活能不能独立并行】；「调研+写码+点评+合成一篇」这类跨域合成流水线少派（常见 1～2 人），勿默认每人一种专长（对齐 compare 跨域溃败实证）。拿不准先少派，不够再加；形状拿不准才 `consult_skill`。**③ 广度调查归团队**：横扫大量来源、可拆多角度的只读调查也扇出并行调研 worker，task 点明「回报精炼结论、不回贴整段正文」。CEO 只读工具只用于开工前探路 + 收尾综述。**注意**：`result_handling` 只管上游→下游注入，**不**影响回到 CEO 的内容。**④ 对抗 solo 塌缩**：提示词路由第一拍（一句定方向）+ 引擎 `team_gate`（调查工具累计 ≥3）：一律硬收调查工具；仍可直答（须给归类理由）或 `delegate`，禁止再搜/再读；成篇调研意图（`is_research_report_intent`）硬停时仍追加形状句（宜 `research_report` / ≥2 角，禁 `none`+单人）；本地改文件探路阈（≥2）独立。曾有的「早期无工具长正文 → 丢弃草稿复核」已撤（误伤正当长直答）。→ 见代码: `runtime/engine/governance.py`
>
> **首轮组队收益实证（2026-07-21 `--compare` 16 用例，5.2 单模型，数据 `apps/server/eval-out/comparison-merged.json`）**：team vs 单体成对裁判——**赢面**：深度并行调研（`par_collab_p1_ai_labs` 单体 passk 全挂 team 全过；`par_rag_survey` 胜率 0.70 且成本仅单体 53%）、技术选型辩论（`dbt_storage_pick` 0.70 零负场）；**同预算对照（matched_single）下 team 成本全部更低（0.21–0.53×）且更稳过硬性判据**——team 的实证价值是「同预算更便宜/更稳过线」，非「更聪明」（裁判在连贯深度上常偏爱单体，passk×win_rate 背离已记档）；**负面**：简单任务组队零增益纯付 3 倍成本（预期内）；**跨域整合 4 用例 team 全面溃败（avg 胜率 0.175）**——产品层已收窄为「按缝拆、跨域合成少派」，见上条团队形态判据。数据质量保留与复跑姿势见 [本地开发 · evals 评测跑法](/docs/02-架构/本地开发.md)。

> **认知分工判据：约束归 CEO、专业方案归专家；派单「指路不代答」 ✅ 已落地**：task 只写【目标·约束·验收】；交付物的【专业方案】与【专业判断】默认归专家 worker，除非用户已明确指定结构。`contract` 是**验收契约**而非结构蓝图。审查类越界：编号「重点关注」清单（含风险预判）不得写进 task 替 worker 作答——正确去处是 `seed_notes`(kind=heads_up)。worker 侧对称：关注点清单是起点线索不是答题边界。→ 见代码: `runtime/resolve/prompt.py`

> **worker 侧其余协作通道**（拓扑位置 / 扇出感知、`escalate` 升级、`handoff` 交接、三档自主度、便签墙）→ 见 [`Agent协作模式.md` §二](/docs/03-AI核心/Agent协作模式.md)。

> **结构跟着证据走 ✅**：调研成篇用 `depends_on` + `checkpoint_after` 把「定结构」摆到调研之后。→ 见代码: `runtime/delegate/`
>
> **轻量直出（finalize）✅**：单 worker + `finalize=true` 成功时 `HANDOFF` 直出，省 CEO 合成轮。→ 见代码: `runtime/delegate/`

> **`complexity_hint` ✅**：`light`/`standard`；引擎可自动推断 light；与深度交付并存时忽略显式 light（`complexity_hint_ignored` 改回 standard）——管编排姿态（如 light 隐含 `coordination=none`），**不**映射 worker token/超时（统一 backstop 见 [执行引擎 · 收敛治理](/docs/03-AI核心/执行引擎架构设计.md)）。→ 见代码: `runtime/runs/worker_budget.py`（深度交付谓词）、`runtime/delegate/`

> **`coordination` 便签墙 ✅**：缺省 `none`。权威全文见 [`Agent协作模式.md`](/docs/03-AI核心/Agent协作模式.md)。→ 见代码: `runtime/delegate/`

> **委派后不重复调查 ✅**：提示词强化「用团队产出写综述」，非硬禁只读。→ 见代码: `runtime/resolve/prompt.py`

> **调研引用：worker 引回合台账 `#rN` ✅ 已落地**：并行调研 worker 与 CEO 共用**回合级共享台账**（登记即拿全局 stable id）；成稿只引 `#rN`，handoff / Delegate 汇入**禁止重写**正文 id（否则重排病复发）。worker 仍 `annotate_citations=False`（不注入会重排的池序号 `[n]`），但经台账拿 stable id 注解 + id 存在闸。CEO 汇总继承同一台账、不得对同一 URL「重新编号」；用户可见角标可用展示层 `[n]`（display map），**n 是展示、id 是真理**。→ 见 [工具与能力 · 引用质量闸](/docs/03-AI核心/工具与能力系统.md)、[执行引擎 · finish_guard](/docs/03-AI核心/执行引擎架构设计.md)。
>
> **主张须证（P3 prompt）✅ 已落地 · 机械闸 ⏳**：调研成稿与 CEO 综述对关键数字 / 关键结论须旁标 `#rN` 或显式待核实语（共享基座 `<claim_evidence>` + CEO `citing_sources`【汇总继承】）；不强迫辩词 `【已核实·#eN】` 二分、不加机械抽查闸（机械闸待观测数据 → 远期规划 §三·主张须证机械闸（详细提案不在公开仓 / 维护者本地））。
>
> **撤销「worker 不编号」**：旧决策因各 worker 本地列表汇入时按到达序重排、正文 `[n]` 会对错卡——根因是「本地起编 + 事后合并」，不是「worker 不该引用」。现状改为共享台账原子 id 后根因消失；**不是**简单打开旧 `annotate_citations=True`。**被否**：handoff 时重写正文 id「对齐」全局编号（等同重排病）。

> **产出形态：文件落盘 vs 文字直出 ✅ 已落地**：worker 按交付【形态】判定写文件还是写正文；CEO 在 task 里点明落盘要求，`ask_user` 开工提案卡也说明最终交付是工作区实文件。→ 见代码：`runtime/runs/executor.py`、`runtime/resolve/prompt.py`、`runtime/skills.py`。

> **落盘契约门 `requires_files` / 声明式 `artifacts` ✅ 已落地**：CEO 可设 `deliverable.requires_files=true`（任意落盘）或 `deliverable.artifacts=[路径…]`（具体文件 / 目录 / 通配）声明文件交付；收尾 `check_contract` 对工作区做存在性对账，未达标自动返工一次；非 strict 时矫正后仍缺则软接受并在 delegate 汇总「契约缺口」段结构化上报。声明了 `artifacts` 的批次自动启用对应完工验收（省略仍=不强制）。**内容检查通道对齐交付形态 ✅**：文件形态交付的章节/关键词/长度检查读「正文 + 本 run 落盘文件」（任一通道命中即满足）。**网页接缝静态检查 ✅**：同批落盘出现 HTML + CSS/JS 时，确定性交叉校验 HTML `class`/`id` 与 CSS/JS 选择器命中率（未命中率超过约三成 → fail → `contract.retry`，反馈列出挂空类名）；普通文档交付不触发；无浏览器。**前端质量门禁 `web_quality_scan` ✅**：独立于 placeholder_scan / web_seam；硬=语法损坏+编造联系方式+DESIGN 对账（缺 DESIGN / 缺风格 id / 散色），软=anti-slop 最多回炉一次。**落盘口径认执行成功 ✅**：`files_touched` 仅在工具成功时记账（失败/拒绝不虚计）。→ 见代码：`runtime/runs/contract.py`、`runtime/runs/web_seam.py`、`runtime/runs/web_quality_scan.py`。

> **否决悬空预留 `Deliverable.output_schema`**：曾作阶段 2 JSON Schema 预留位，无 schema 入口、不校验——假能力已删除；路径级验收由 `artifacts` 清单承载。

> **CEO 提示词分层 ✅ 已落地**：常驻 = 路由脊柱 + 能力目录 + 短钩子；进阶 HOW 在系统 Skill，用时 `consult_skill`。**分层不变量**：同一条知识只在唯一所有者出现。要点：① 核心只写工具**边界**（只读 / 检索 vs 改东西须 `delegate`），不手抄工具名——真名以本回合工具列表 / 注册表为准；② consult 强度**按场面**（多人 / 套 playbook / 没把握 → 必查 `team_orchestration_advanced`；单人清楚可 finalize → 可不查），核与目录 preamble 同句（`CONSULT_TEAM_ORCH_BY_SCENE`）；③ 开场 `ask_user` = **开工提案卡**，`team_preview` = 口语「开工卡」/ 团队预览，勿混名；④ 引用：共享底管「`#rN` 真假引擎查」与「主张须证·暂靠提醒」，CEO citing 只管汇总继承。→ 见代码：`runtime/resolve/prompt.py`、`runtime/skills.py`、`tools/builtin/ask_user/`。

> **冷启动探索幕 ✅ 已落地（P0+P1+过期再探）**：有项目（`folder_id`）+ 实质请求 +（项目 `画像.md` 空 **或** `_memory_meta` 中 `explore_workspace_key` 与当前绑定不一致）→ CEO 提示注入 `<cold_start_explore>`（空仓建档 / 绑定已变两套文案），须先轻量探路 → `delegate`（`team_preview`）组调研队 → 收尾 `update_project_profile` 合并写入项目画像并记录 `workspace_key`（可选 `topics`≤3；本回合工具回灌 + worker prompt 热补丁可见）→ **立刻继续原请求**。用户点名「先了解 / 重新了解 / 刷新项目记忆」强制开幕（合并更新）。旧画像无 key → 不因缺 key 硬开。裸聊 / 纯闲聊 / 空工作区不自动开幕、不写假画像。不新建 Explore 原语；指纹/天数/commit 自动重探不做。→ 见代码: `memory/explore_profile.py`、`tools/builtin/update_project_profile.py`、`runtime/resolve/prompt.py`、`runtime/pipeline/assemble.py`。

> **CEO 工具面瘦身（schema 短触发 + 条件注入）✅ 已落地**：① 长描述迁入 `consult_skill` 渐进披露，schema 只留短触发句 + 关键参数；② **闲聊态**不向 LLM 注入 `replan` + 协调四件套——注入闸与协调工具执行闸对齐；`delegate` / `ask_user` / `debate` **常驻**；进入协调或经典波边界让出时回合内补注册。→ 见代码: `runtime/resolve/ceo_surface.py`

**为什么是档2.5（结构取档2；档1「全能 CEO」、档3「纯编排 CEO」被否决）：**

- **档1（CEO 持全套工具，仅复杂任务才委派）**——CEO 上下文易被大块工具输出污染，长会话越来越贵，「团队协作」心智被弱化。
- **档3（CEO 只剩 `delegate`，连检索都过 worker）**——仍否决：把**高频的轻量只读**（单点确认 / 探路）也压上 worker 往返，会给 95% 的轻量路径平白加一层延迟与成本。**但原否决理由里「检索大输出不进 CEO 上下文」一句须修正**：历史重建（工具 I/O 不跨轮回放）只清理**跨轮**残留；**回合内**一场广度调查的几十次只读仍会实打实堆进 CEO 当前窗口、把它撑大。这恰恰说明「广度调查该扇给团队」——但这归**委派判据**解决（即 2.5 的路由细化 + 运行期软护栏），而非靠抽走 CEO 的检索工具（那会误伤高频轻量路径）来解决。
- **档2.5 取中**：保留档2 结构的两份收益（团队心智 + CEO 上下文洁净），同时把路由判据从「交付物 vs 对话」纠正为「直答 vs 委派」——既不让轻量只读背上委派税，也不再放任 CEO 把成规模的广度调查独自串行做完；单 worker vs 多 worker DAG 的复杂度梯度下沉到委派内部，不再作为路由层分类。

### 实现方案：自研编排，不依赖第三方框架 ✅ 已确定

| 设计点 | 决策 |
|--------|------|
| 编排器定位 | CEO 主 Agent 的「按需规划能力」：CEO 既对话又规划；简单请求直接答，复杂任务才下达计划 |
| 调度形态 | DAG 连续依赖调度：`delegate` 的 `depends_on` 定形；`WaveScheduler` 就绪即发射（不等同波其余节点），仅在决策边界（波边界）让出监督 |
| 输入 | 用户请求 + 可用工具清单 + 会话历史（CEO 在 ReAct 循环内掌握） |
| 输出 | CEO 在 ReAct 循环里调用 `delegate(tasks=[…])` 下达子任务（见下「delegate 原语」） |

**为什么自研（被否决：LangGraph / CrewAI 等框架）：** ① 编排是 AgentCore 的核心壁垒，必须完全掌控；② 第三方框架的抽象与「Agent 团队管理」心智模型不完全匹配；③ 避免框架锁定。

### 聊天优先 + 按需编排 ✅ 已确定

入口即 **CEO 主 Agent**（默认走快的 `chat` 档），它直接拥有并回复对话。只有当 CEO 判断某请求**确实需要一个团队**（多视角并行、设计→实现→测试流水线）时，才调 `delegate` 下达子任务、执行 DAG，并由 CEO 自己收尾汇报（需对抗性多视角思考的辩论 / 对比另走 `debate` 编排工具，见 [`辩论编排设计.md`](/docs/03-AI核心/辩论编排设计.md)）。

| 场景 | 路径 | 用户感知 |
|------|------|---------|
| 简单对话 / 问答 / 单点检索 | CEO 直接流式回答（零编排开销） | 首字即时，体验同 ChatGPT |
| 需要产出 / 变更，或需要团队的复杂任务 | CEO 调 `delegate` → worker（单个或多 Agent DAG）→ CEO 收尾汇报 | 协作面板展开，展示分工；全程一个声音 |

升级由模型自决：CEO 每轮都在，自己判断要不要组团；误判时优雅降级——不调 `delegate` 即等价单 Agent 直答，不空转组团。

> **被否决：编排器是唯一入口（无前置分类器，每轮必经编排器 LLM）。** 原方案让每条消息（哪怕「你好」）都先付一次完整编排器往返，实测对简单输入也有 ~15s 首字延迟，95% 对话的编排纯属高频聊天的「税」。改为「聊天优先 + 按需编排」后，编排开销只在真正需要团队时支付，对齐 Claude Code（Task 工具）、OpenAI Agents SDK（agents-as-tools）的行业范式。原方案「避免两套决策逻辑不一致」的诉求，改由 CEO 统一承担「每轮判断是否升级」来满足。

---

## 一、`delegate` 原语（D1′ / D2 / D3）

CEO 在自己的 ReAct 循环里调用单一的 `delegate` 工具把一批子任务交给内联 worker——**图由 CEO 在循环里增量声明**，非外部一次性 JSON 计划。

### 自选粒度（D1′）

`delegate(tasks=[…])` 的 `tasks` 由 CEO 自定批量：

- **一次塞 N 个** = 全景计划（一批声明完整分工）
- **同回合再调一次** = 动态追加（合并进【同一张】协作图，同 `execution_id`；协调模式下不必等上一批全部完成）
- **跨回合追加** = `delegate(append_to_execution_id="latest" 或上一张图精确 id)`：复用该 `execution_id`，在旧图上 merge 新节点并继续流式；新回合只发 `graph_append` 锚点（「已往上方协作图追加 N 名成员」），生长帧续写宿主助手消息的 `turn_journal`。图完成/收拢由该 execution 自身的 run 终态决定，**不**随追加回合的 `message_end` 结束。与 `continue_from_run_id`（唤回某 worker 会话记忆）正交。

**追加目标解析与回显（拿 id 通道）**：history 重建只回放 user/assistant 正文、丢弃 tool I/O，模型跨回合抄不到 `execution_id`——所以主路径是**服务端解析**：`append_to_execution_id="latest"` 由引擎解析为本对话最近一张**可追加**协作图（`turn_journal` 中最新的 `plan_type='multi_agent'` `run_plan`，排除当前回合；辩论图不可追加；仅根协调者 `depth==0` 可追加——嵌套 lead 会跨图串写，显式拒绝）。解析失败返回明确错误、**禁止静默新建图**——文案按真相分两支（`tools/builtin/delegate/tool.py`）：本回合已有**活跃协调会话**（`active_coordination(execution_id)`）则引导「同回合追加无需 `append_to`，直接再调 delegate 会自动并入当前协作图」（`"latest"` 排除当前回合故必解析失败，但同回合再调走协调 merge 并非新建，旧文案会让 CEO 谎称新组建团队）；无活跃会话才引导「改新建图并如实告知用户本次是新组建团队」。回显通道两条：① 每次 `delegate` 结果尾注回显本图 `execution_id`（建图与追加均回显，当回合可见）；② 下一回合起 CEO 系统提示**易变尾**注入 `<recent_team_graph>` 注记（本对话最近一张图的精确 id，CEO-only，不进 worker base）。多图并存要点名旧图时填精确 id，**显式 id 优先于 latest**。

**CEO 行为口径（何时追加 vs 新图）**：默认每个新回合新建图；仅用户**显式表达延续意图**（「往上一个协作图 / 那支团队继续加人 / 接着干」）才追加（以 `"latest"` 省略 id 形式为主）。收尾文案与产品呈现一致：追加成功说「已往上方协作图追加 N 名成员」（生长呈现在上方旧图，追加回合只显示锚点条），禁止「在同一回合的同一张图里」等与呈现不符的承诺；新建图时不得说成已在旧图上追加。教学载体：CEO core `【跨回合延续】` 段 + `team_orchestration_advanced` skill + delegate schema。

同一工具 / 同一 schema / 同一调度，CEO 自选委派粒度。**真正的不变量是「一张协作图一个 `execution_id`（可跨回合生长）」**——不是「一次只能一个 delegate、同步阻塞到全队完成」，也不是「每用户回合必新开图」。并行度由**节点的 `depends_on` 数据声明**（无依赖即同波并行），而非靠模型主动发并行 tool call。

**开新幕 = 机制携带，非 CEO 参数**：幕序列图（协作图 = 幕的序列，契约见 [`执行引擎 §二·幕序列契约`](/docs/03-AI核心/执行引擎架构设计.md)）里辩论幕的追加**不走** `append_to_execution_id`——开工卡 / 阶段推进卡决议机制携带宿主 `execution_id` 直起新幕（`debate` 工具无感，见 §五·阶段推进卡；挂点语义见 [`辩论编排 §7.3`](/docs/03-AI核心/辩论编排设计.md)）。

→ 见代码：`runtime/delegate/graph_append.py`、`tools/builtin/delegate/`；契约向量 `multi_agent_cross_turn_append`。

### 终态语义：非终态，CEO 收尾（D3 + 决策①）

`delegate` **默认是非终态工具**：worker 跑完后，结果交回 CEO 的 ReAct 循环，CEO **用自己的声音**写最终答案（`content_delta`）。**例外（finalize，提案2a ✅）**：当 CEO 对一个单 worker 的最终交付设 `finalize=true` 且该 worker 成功时，`delegate` 转为**终态**（`ToolEffect.HANDOFF`）——把 worker 产出直接推到气泡作为回合答复，不再触发 CEO 合成轮；多 worker / 失败时仍按非终态由 CEO 收尾。见上文 §协调者工具边界「轻量直出」。

> **决策①**：CEO 只写**一段简短概览**（综述关键结论、串起整体、指引用户看细节），**不复述各 worker 全文**——每个 worker 的完整产出由前端单独展示（run 详情 / 图视图）。这消解了「CEO 重读全文合稿」的开销。
>
> **被否决：SYNTHESIS 合稿节点**（在 plan 末尾挂一个独立合稿 Agent）。合稿仍是「循环外一趟」，正是 CEO 模型想溶解的形态；`react_loop` 现成支持「工具返回后继续循环」，无需独立节点。

#### 协调模式（默认开）✅ 已落地

多 worker 且根 CEO（`depth==0`）、非 `finalize` 时，`delegate` **默认**立即返回「团队已启动」，`WaveScheduler` 后台跑；CEO 继续 ReAct，消费团队事件（完成 / 便签 / 升级 / 超时 / 全部完成）并在有语义增量时用 `update_synthesis` 合成中间稿。同回合再调 `delegate` = 往**【同一张】协作图**动态追加 worker（同 `execution_id` 合并），**不必**等上一批全部完成。传 `coordinate=false` 显式退出到经典阻塞；单 worker、`finalize`、嵌套 lead（`depth>0`）、批含 `checkpoint_after` 且把关闸开 **仍走阻塞语义**。

**生命周期与回合解耦（异步团队）✅**：协调 session / 后台 drive 寿命不绑聊天回合；后台自建自关独立 LLM client；**SSE 断连** teardown **不得** `clear` 仍在跑的 session（detach 续跑）。**显式 user `/stop`** 例外：级联取消协调 drive 与全部在跑 worker，已完成产出保留进收口消息（终态由 `incomplete` / `finish_reason` + 前端状态条呈现；正文不再写括号说明）。→ 见代码: `runtime/coordination/session.py` `cancel_coordination_on_user_stop` / `release_turn_coordination`、`runtime/turn_runs.py` `stop`、`runtime/turn_interrupt.py`。

**异步团队产出投递（批次 1）✅**：执行升格为对话级实体，回合只是观察窗口。四支柱：

| 支柱 | 决策 |
|---|---|
| A · 展示事实 | `run_started` / `run_completed` 等 DURABLE 经 execution 绑定的宿主 journal writer 落盘，不依赖回合 sink 存活；SSE 推送 best-effort。重开对话 fold 可重建协作图与队员正文 |
| B · 路由 | 「conversation → 活跃 executions」注册表为停止 / 插话 / append / 新回合归属的唯一源；ContextVar 仅单任务树缓存；跨任务边界显式传 `execution_id` 或 `adopt_active_execution` |
| C · 收割 | drive 终态且无附着回合 → 发 `execution_completed` → 系统收口回合（`run_and_persist` 先例）收养 session、消费 `ALL_COMPLETED`、CEO 合成终稿为新助手消息 + 推送通知（`origin=execution_harvest`） |
| D · 协议 | 新增 `execution_detached` / `execution_completed`（DURABLE）；CEO 提前收口允许但须显式转后台（发 detached）。v1 前端静态「后台运行中」+ 完成后刷新；**窄版 D1**：有 live detached drive 时 sink 延迟 close 至 drive 终态（`run_completed` / `execution_completed` 仍可 live 推送）；对话级实时字数通道二期 |

空转巡查：worker 忙碌时不发假 TIMEOUT nudge；短等后让出空轮给 CEO（`idle_yield_to_captain`），保留中途 `ask_user` / 显式转后台能力。→ 见代码: `runtime/coordination/harvest.py`、`conversation/execution_harvest.py`、`runtime/events/sink.py`、`runtime/coordination/wait.py`。

**空转巡查活性检查 ✅**：协调等待 idle 超时拟注入巡查 nudge 前，先查 execution 内 worker 是否有 in-flight LLM/工具调用——有则不发 nudge（短等后让出 CEO）；真停滞（无进行中调用）仍巡查，且 nudge 附带各 worker 进展摘要。→ 见代码: `runtime/coordination/wait.py`、`session.mark_worker_busy`、`engine/loop.py`。

**空转让出简报 ✅**：`idle_yield_to_captain` 不再空手让出——注入流水线进度简报（波次 × 节点态：在跑 / 依赖阻塞 / 待调度 / 失败；所有协调注入均随带同一进度块），流水线健康（有在跑、其余仅依赖阻塞、无失败）时明示「正常推进·无需追加动作」，防 CEO 把依赖等待误读为空闲而追加重叠队员（GEO 官网事故教训）。→ 见代码: `runtime/coordination/pipeline_view.py`、`runtime/coordination/inject.py`。

**再委派护栏 ✅**：活跃协调上二次 `delegate` 若与在跑队员**角色+任务同构** → 结构化拒绝（须显式 `force=true` 才放行）；增量合并进活跃协调**同样走** `team_preview` 开工卡，不得静默并入。→ 见代码: `runtime/coordination/isomorphic.py`、`runtime/delegate/drive.py`。

**追加重叠守门 ✅**：同构拒绝之外，协作图追加的 `delegate` 若与在图节点**角色职责**重叠（仅未完成节点）或**文件归属**重叠（C3：含已完成 owner 的会话归属表）→ 结构化拒绝并引导（等波次推进，或 `cancel_worker` / `replan` / `replaces_run_id` 显式接手后再派）；流水线外新增职责放行；`force=true` 旁路或强制转移。**不变量**：同批 sibling 交付物交叉与上述同类准入闸均在 durable `run_plan` emit **之前**（准入→提交→执行）；契约拒绝零图副作用。动因：GEO 官网事故——CEO 空转唤醒后追加重复文案 / 整站前端 / 重复 QA，与骨架节点抢写 `site/index.html` 触发写冲突。→ 见代码: `runtime/coordination/append_guard.py`、`runtime/coordination/host.py`、`tools/builtin/delegate/tool.py`。

| 约束 | 决策 |
|---|---|
| 启用门 | ≥2 worker + 根 only + 非 finalize；显式 `coordinate=false` 退出；**批含 `checkpoint_after` 节点且 checkpoint 闸开 → 不进协调**（B1 解法：把关卡必须 durable 弹给用户，强制经典阻塞路径；闸关如 evals 时不受影响） |
| 图不变量 | **一张协作图一个 `execution_id`**；同回合多次 `delegate` 追加合并；**跨回合**经 `append_to_execution_id` 往上一张图继续生长（复用同 id，非新开图） |
| 追加队员 | 同回合：协调进行中 → 再调 `delegate`；波边界 → `replan(add=…)`。跨回合：`delegate(append_to_execution_id="latest"/精确 id)`，服务端解析 + 回显见 §自选粒度（与 `continue_from_run_id` 正交） |
| 合成通道 | 草稿走 `team_synthesis_preview`（`in_progress`）；终稿仍 `content_delta`。**职责分工（2026-07 拍板）**：完成计数 n/m 与各队员完成摘要由确定性通道自动呈现（`coordination_wait` / 协作图 / worker blurb），CEO **不**为播报进度调 `update_synthesis`——仅语义增量（新中间结论 / 产出冲突 / 方向修正 / 长跑阶段性收束）才更新；纯进展事件静默监听（无正文无工具），协调活跃期的静默轮**不进** B2 空响应梯子（`engine.coordination_listen`，见 [执行引擎 §四·收敛治理](/docs/03-AI核心/执行引擎架构设计.md)）。动因：测试对话实证 CEO 逐 worker 完成小改草稿（间隔中位 8.4s、draft 增量中位 +22 字），带 `update_synthesis` 的轮次占 CEO input tokens ~39% 而信息增量低 |
| 等待感知 | CEO 在 `await_coordination_injection` **真实空等**时推 `coordination_wait`（EPHEMERAL：进入 `waiting=true` / 退出清除；长等 ≤15s 刷新 `completed/total`）；前端 StatusStrip / CEO 汇聚点显示「等待团队成员完成 (n/m)…」。立即 drain / 终态短路不推，避免闪烁 |
| 挂起 | **`team_preview` 在 coordinate fork 之前**挂起即收口（开做后续跑再臂后台）；**增量委派（合并进活跃协调）同样过开工卡**。协调中 `ask_user` 软挂起即收口；状态入 journal，续跑重建（不保活后台调度器）。`checkpoint_after` 波边界**不** durable `plan_review` 收口——只发 `BOUNDARY_YIELD` 协调事件（正常路径已由启用门排除，仅 replan 中途加把关节点等残留场景走到，注入文案强制 CEO 转 `ask_user` 拍板）；经典阻塞（`coordinate=false`）仍挂起即收口 |
| Phase 3 | 超时只通知不自动取消（先 warn 收尾窗口、再 TIMEOUT 通知）；非阻塞 escalate / 便签冲突进事件队列；SCOPE 边界 PROCEED 由 CEO 仲裁；**阻塞 escalate 改 CEO 仲裁**（`resolve_escalation`；偏好/授权/费用类先 ask_user 再 resolve） |
| 用户插话 | 协调运行中用户新消息进 session 队列（必要决策点，必唤醒）；CEO 智能路由——**相关入图**（`update_synthesis` / 再 `delegate` 追加 / `cancel_worker`），**无关转排队**（`queue_user_message` → 对话级队列，下一回合处理）。插话可带附件：到达即落盘工作区，简报只给「名字 + 路径 + 二进制标记」，CEO 自己 `file_read` 或把路径写进 steer 指令递给队员。经典阻塞路径无协调窗口，消息一律排队（实时改向用既有 `run_redirect`），**否决**「为插话把单 worker 升格协调」（改动大收益小） |

**不变量 B（CEO 仲裁 ⇔ 协调存活）**：`resolve_escalation` **仅**在协调 session 活跃时可用。单 worker / `finalize` / 嵌套 lead / 显式 `coordinate=false` 走经典阻塞——CEO 卡在 `delegate` await 上、波内无活着的 CEO，阻塞 escalate **直挂用户**（`awaiting=user`），**绝不**改挂 CEO（否则 worker↔CEO 死锁，只能靠超时回落）。测 `resolve_escalation` 必须 ≥2 worker 进协调。否决「单人也 awaiting=ceo」除非先改 drive 让单人亦保 CEO 存活（真·A，未做）。

**不变量 C（终态必达 + 终态对账）✅**：`drive` 的**所有**终态路径都必须投递 `ALL_COMPLETED`（或强制取消的 `DRIVE_CANCELLED`）。**主保障（批次 4）**：每个 execution 终态必须收敛到「附着回合注入」或「收口回合 harvest」二者之一，未收敛 → `coordination.terminal_unsettled` error 告警。host 终态回填与 wait team-done 短路降为**竞态兜底**（warning）；等待耗时观测 `coordination.wait_end`。→ 见代码：`runtime/delegate/drive.py` `_post_session_all_completed`、`runtime/coordination/session.py` `check_terminal_settlement`、`runtime/coordination/host.py`、`runtime/coordination/wait.py`。

**决策（为何 CEO 自协调）**：通用协调走 **CEO ReAct + 事件队列**，不引入独立协调 / 合成 Agent（延续上文否决 SYNTHESIS），也不复用辩论 Moderator 的确定性循环——CEO 已持完整用户意图与元权限（`replan` / `cancel` / `ask_user`），独立协调者只会多一层意图损失；Moderator 继续专管辩论。成本纪律见 [执行引擎 §协调模式例外](/docs/03-AI核心/执行引擎架构设计.md)。

→ 见代码：`runtime/coordination/`。

> **文件产出清单（收敛免回工作区核对）✅**：`delegate` 汇总附各 worker「文件产出」行，CEO 据此收尾、不必再 `file_list` 回工作区核对。→ 见代码：`runtime/runs/executor.py`、`runtime/delegate/`。
>
> **同一清单兼作防幻觉凭据（footer 守卫）✅**：清单为空时 CEO 不得报「已创建/已完成」，应带现场续派唤回或重派。→ 见代码：`runtime/delegate/`。

> **回合级「下一步推荐」(CEO→用户) ✅ 已落地**：回合收尾后另发 2-4 条可点选的快捷追问（下一步建议）挂在助手回复下，点选即回填输入框、可改后发——CEO→用户收尾面的延伸（与 §核心定位「收尾向用户汇报」一脉）。它是 worker→CEO「交接简报·建议下一步」的用户侧对偶。机制（finalize 的 World B 窄任务 + `followups_generated`（含 `message_id`）事件、DERIVED 回写 `Message.followups` 列故重载重现、桌面+手机+画布均有）见 [`执行引擎架构设计.md` §回合级「下一步推荐」](/docs/03-AI核心/执行引擎架构设计.md)。

### 收尾即验收：合·验证两道 ✅ 已落地

CEO 收尾从「写综述」升级为「**先对账拼图边、再核验原始目标、最后写概览**」——纯提示升级（不加人 / 不加新暂停 / 不新子系统），落在 CEO 既有看产物的接缝。两道与既有各闸**显式分层不重叠**：per-piece `contract` 管单块达标、**4b** 管块间拼接、**4a** 管整体达成原始意图、防幻觉铁律管文件真落盘。

- **第一道（4b）· 语义边界对账**：在三处接缝先对「拼不拼得上」——**只查冲突 / 缺口 / 重复，不评每块好不好**：① `format_for_ceo`（合并前；CEO 自判「相互依赖、要拼到一起」才查，独立并行跳过）；② `supervised.py::format_bind_boundary`（定稿下游前对上游，catch-early）；③ `format_scope_boundary`（队员报偏离时主动查兄弟接缝——即「`escalate scope` 等举手」的**主动版**）。对出问题就地续派/`replan`/`ask_user`，别在概览里糊过去。判据同便签墙：块间有没有共享接口 / 相互依赖。
- **第二道（4a）· 成品对照原始目标 + 完工判定**（实证 ROI 最高）：写概览前对照【用户原始请求 + 各 task 的任务描述与 `deliverable`】逐条核验「实质达成」，给明确**完工判定**——未达成就 `delegate`（冷委派或带现场续派）/`replan` 补、别假装收工；已达成就收口、别空转。直接对治 MAST 实测两大失败（不认终止条件 / 过早终止），其「加高层目标验证 +15.6%」是全表 ROI 最高的单点干预。
- **一处覆盖两条收尾路径**：改 `ceo_format.py::format_for_ceo` 即同时盖正常终态综述（`drive.py`）与 `replan(stop)` 收尾（`supervised.py::finalize_stopped`）；【团队便签】（便签墙 `active_notes`）正是 4b 的现成输入（见 [`Agent协作模式.md` §波内共享上下文](/docs/03-AI核心/Agent协作模式.md)）。
- **`audit_gate`（引擎旁路）✅ 已落地**：与 4a/4b **分层**——4a/4b 是收尾提示自检；`audit_gate` 是质量敏感成品上的「换人审」激励/硬闸。软门（`audit_gate_nudge`）：captain、首批 substantial、尚未 fire 时注入一次 nudge（成篇/构建/审查类宜派审计者≠作者；可给归类理由后直接交付；**系统绝不代派**）。硬门：`research_report` / 计划呈长文·字数承诺等信号，且批内尚未含审校路径时挡 `end_turn`。协调 `all_completed` 亦可再提醒。用户无独立「审计」UI 卡——文案进 CEO 消息旁路，终稿不得粘贴系统提示。
- **暂不建（开放项）≠ 否定 audit_gate**：人 2026-06-30 否决的是高风险「**独立验证回合子系统**」（每高风险回合强制新机制 + 真成本、与 4a 叠床）。**不等于**禁止引擎旁路式审计门；现状用 `audit_gate` 软/硬门覆盖「换一双眼睛」激励，不另起验证子系统。若未来要升格为强制独立回合，须先有度量证明 CEO 自检系统性漏「自己批自己」。→ 远期项见维护者本地规划（不在公开仓）。

→ 见代码：`runtime/delegate/ceo_format.py`（`format_for_ceo`）、`runtime/delegate/supervised.py`（`format_bind_boundary` / `format_scope_boundary` / `finalize_stopped`）、`runtime/engine/governance.py`（`audit_gate_*` / `maybe_inject_audit_gate`）。

### execute 流程（概念）

→ 见 [`执行引擎架构设计.md` §三](/docs/03-AI核心/执行引擎架构设计.md)（`delegate` → `build_run_plan` → `WaveScheduler`）。

### `replan`：波边界续跑（第三编排原语）✅ 已落地

`delegate`（含带现场续派）之外的第二个编排原语。当计划含**晚绑定节点**（`bind_after_deps`）或队员报告**职责偏离**（`escalate kind=scope`）时，`WaveScheduler` 在决策边界把控制权交回 CEO——`delegate` 输出**非终态**「计划已让出」简报，CEO 调 `replan` 定稿 / 纠偏 / 追加 / 收口后**续跑同一张 DAG**。执行语义（边界判据、`YIELD` 软暂停、晚绑定、成本纪律、被否决项）见 [`执行引擎架构设计.md` §受监督的波循环](/docs/03-AI核心/执行引擎架构设计.md)；此处只记 CEO 侧的工具形态与设计理由。

| 参数 | 语义 |
|---|---|
| `binds` | 把 `bind_after_deps` 占位节点定稿（据上游产出补全 role / task / objective / deliverable 等），定稿后该步即可运行 |
| `steers` | 给【尚未运行】的下游追加操舵说明（同 `plan_review` adjust 机制，运行前注入）；已完成步骤不可操舵 |
| `add` | 追加初始计划没预见的【全新】节点——`build_added_nodes` 管 id 生成（每批新前缀、绝不复用）、依赖接线（可指向现有节点或本批内其它新节点）、拓扑校验（未知依赖 / 重复 id / 超额 / 成环即整批拒绝） |
| `stop` | 确认无需继续——未跑步骤记 SKIPPED、已完成产出交回 CEO 收尾 |

> **all-or-nothing**：一次 `replan` 的 binds + steers + add 先全量校验，任一非法则整批拒绝、暂停计划零改动（`apply_replan`）。
>
> **薄封装、共享账目**：`ReplanTool` 持本回合的 `DelegateTool` 并转发 `DelegateTool.replan`——后者持暂停态（`_supervised`）、校验、in-place 再绑定与续跑驱动；故 worker usage / 账目 / 来源累加在**同一个 `DelegateTool` 实例**上、被回合总账折算，`replan` 自身无账目面。
>
> **被否决**：① **把 `delegate` 重载成「续跑旧计划」入口**（语义混淆「发起 / 追加任务」与「波边界续跑」——后者专属 `replan`；**不**禁止同回合多次调用 `delegate` 往同一张图追加）；② 复用带现场续派（那是在 worker transcript 上续写、非计划续跑，见 [`多轮编排与同人续派.md`](/docs/03-AI核心/多轮编排与同人续派.md)）——故 `replan` 独立成工具。`add` 早期曾计划推迟，现已与 binds / steers / stop 一并落地。
>
> → 见代码：`tools/builtin/replan.py`、`runtime/delegate/supervised.py`（`apply_replan` / `finalize_stopped` / 边界简报）、`runtime/runs/builder.py`（`build_added_nodes`）。

### `playbook`：固化高频拆解形状 ✅ 已落地（二分：只锁建站）

少数**高频、高方差**的拆解形状从散文指引提升为**可实例化的一等流程**。任务怎么拆只认两种主人：**系统锁（流水线）** vs **团队自由组队**——第一期只锁建站；调研 / 做功能 / 多透镜等为可选形状对照，不强制声明、不设「优先」中间档。

- **纯加法、不加子系统**：`runtime/runs/playbooks.py` 一个小注册表（`name → builder(slots) → tasks[]`，纯函数），产出就是 `build_run_plan` 已吃的 tasks 形状，故实例化出的 playbook 走**与手搓完全相同**的管线（`build_run_plan → drive → executor → ceo_format`）。
- **注册表形状（可选快捷）**：① `research_report`（N×调研 →〔可选 checkpoint〕提纲 → 写作）② `build_feature`（后端接口 →〔前端页面 ‖ 测试〕并行，接口契约经便签墙广播）③ **`build_website`**（文案 → 设计契约 → 骨架+契约 → N×分区补丁 → 独立 QA；营销官网确定性骨架，默认 `coordination=wall`）＋ **`build_website_verify`**（第二段整页/视觉 QA-only）＋ **`build_toolshed` ✅**（同五波；控制台/工具台 dense；pack `tool_dense`）④ `compare_options` ⑤ **`multi_lens_research`（MLR）**（并行异构透镜 + 汇总员 → 命题卡）。非建站具名 playbook **保留可选快捷展开**（纯加法、不强迫）。
- **playbook 二分 ✅**：建站 / 落地页 / 营销【必须】`build_website`；控制台 / 后台 / 工具台 dense【必须】`build_toolshed`。其余自由组队：**可不传 playbook**，直接手写 `tasks`（`playbook_none_reason` 可选，不强制）。具名形状与 `tasks` **二选一**展开；未知名 / 缺必填槽 / 二者同传 → 校验报错。任务书只传事实输入（品牌 / 受众 / 素材 / 用户明示偏好），禁自拟视觉施工图。声明入结构化日志 `delegate.playbook_declaration`（记是否走了建站流水线）。**已撤**：全局「每次必填模板或 none+理由」；调研 none 预算收紧；全局教法「优先 research_report / build_feature / multi_lens_research」。**软偏好回潮（非硬锁）**：仅成篇多角取证报告 → 宜 `research_report`（见下教法口径）。
- **建站意图硬闸（方案 C）✅**：绿场建站 / 工具台意图下**机制拒绝** `playbook_id="none"` / 缺省手写 tasks 旁路（机读拒调 + 引导改用 `build_website` 或 `build_toolshed`），堵住「`consult_skill` miss → none + 内容/前端两节点」绕过 P1 管线。意图信号 = 用户原文 ∪ 本拍 tasks / `playbook_none_reason` / `playbook_args` 的**构建向**匹配（做/建…+官网/落地页/website… **或** 控制台/工具台/admin…；审计任务里裸提「官网」不触发）；**续派禁 none（修订 7）**：用户「继续完成 / 补全分区…」类短句 + call 呈建站形（官网/HTML/CSS/`build_website`…）→ 同样拦 `none`（引导改用 `build_website` / `build_toolshed` / `build_website_verify`）；纯「继续」改配置、审计 followup 豁免仍有效。误伤策略：本拍若为审计/修复框定且 call 自身无绿场构建意图 → 豁免。能力目录注册系统 Skill `build_website` / `build_toolshed`，`consult_skill` 可命中。**提示面 A1 ✅**：CEO 常驻 / 能力目录 / delegate schema / `team_orchestration_advanced` 只留 consult 指针；程序权威在 skill body + `ask_user_kickoff` style 硬约束；机制拒文保留。回归锚：`trace_id=7b39eb17c4314f1cbf76a3c84d2c365e`。→ 见代码: `runtime/delegate/playbook_declaration.py`、`runtime/runs/website_style.py`（`is_site_build_intent` / `is_website_continuation_intent`）、`runtime/skills.py`。
- **软件薄 HTML 窄硬拒 ✅**：做软件 / 应用意图下禁止「单前端 + 单 HTML / 仅因单文件缩成 1 worker」旁路（质量兜底，非系统锁）；可手写多角色工程拆分或选用可选形状 `build_feature`——**不**文案强推「优先」。用户开工卡已确认交付形态时可豁免。回归锚：`trace_id=0483b9ecd2734d3daafd142b05cafd98`。→ 见代码: `runtime/runs/software_app.py`。
- **`build_website` 落盘契约 ✅**：五波次不可减（copy→design→skeleton→sections→assemble→qa）——① **文案恒单 worker** 落 `site/copy.md`（**取消双文案分裂**，修订 7）；文案首步 **visual thesis + 文案先行**，注入 anti-slop 黑名单（与扫描指纹同源）；验收用结构化 `required_sections`（禁高 `min_length` 冒充质量）② **设计契约**节点 `depends_on` 文案节点，落 `site/DESIGN.md`（色板 tokens / 字体 / 间距 / 对比度策略 / 禁止项 / **用户选定风格 id**）；骨架与分区只读 DESIGN，禁散写 hex ③ 骨架工程师 `depends_on=["design"]`，落 `site/index.html` + CSS/JS 空壳 + `site/CONTRACT.md`（class/组件契约，便签广播）；**P1b** 骨架从内置营销 catalog 选自搭空壳（任务书注入 id/路径/摘要 + 壳正文），CONTRACT 记 catalog 指针；骨架 `web_quality_scan`+`soft_exempt`（只跑 DESIGN/语法 hard）④ 分区 worker 按**确定性相邻分组**持有分区（见下条；**实现宽≤2**），仅 `str_replace`/`file_append` 补丁既有骨架、只读 DESIGN + 文案（禁整文件重写、禁单 worker 包整站、**禁另起 nav/button 等基础 UI**）；任务书强制 catalog 指针；`web_quality_scan` 门禁（**不做**「必须用了某壳」硬闸）⑤ 独立 QA 回读全部产物核 HTML↔CSS↔JS 接缝 + 前端质量扫描；**P1c** QA 默认 `visual_critic`：hard 通过后多视口截图 → 独立 `VisionReader` critic（对照 DESIGN + anti-slop），critical 至多 2 轮定向回炉，其后 partial；无 browser / 无 vision → 明示未目验、禁谎称视觉 QA 通过。**质检预算（修订 4）**：同对话底线=分区落盘时自动检查；整页/视觉验收可同波，油尽则 `qa_deferred_budget` 诚实 defer → `delivery_status.actions` 发 `website_verify`（prompt 续派 `playbook=build_website_verify`）+ 桌面完成条件卡一键发送——**禁止**再加大 `delivery_reserve` 当主修复。全节点 `form=files`。教训：CEO 手糊「内容→前端」两节点无 QA → 烂页；GEO 官网 8 段满扇出 + 单文案 worker 预算逼顶。
- **前端质量门禁 `web_quality_scan` ✅**（独立于 placeholder_scan / web_seam）：硬失败 = 浅层语法损坏（未闭合标签 / 坏 CSS 声明）+ 编造联系方式指纹（假 400 电话 / 假 ICP / 占位邮箱）+ **填充分阶段**未替换 catalog `{{…}}`（骨架 soft_exempt 放过空壳；分区/QA 硬拦）+ **P1a DESIGN 对账**（缺 `site/DESIGN.md` / 缺「用户选定风格 id」/ 实现散色 ⊈ DESIGN tokens；**`var(--token, #fallback)` 默认色不计散色**）→ `contract.retry`；软 = anti-slop 视觉指纹，最多回炉一次后降为 warning（用户明示风格可 `web_quality_soft_exempt` / 按 label 豁免；**P1a 不改 soft_accept 语义**）。纯静态、零新依赖、禁浏览器。→ 见代码: `runtime/runs/web_quality_scan.py`、`web_quality_rules.py`、`website_style.py`。**风格双闸 ✅**：建站 kickoff `ask_user` 强制非空 `style_options`（id=`s0/s1…`，否则拒调）；resume **结构化 wire**——显式 `style_id`（优先）或 `selected` 中合法 `sN` 记账，**禁止**纯 note/散文模糊匹配独过闸；非法 `style_id` 拒收；`build_website` / `build_toolshed` 无记账则拒调（`full_auto` 窄豁免落默认风格）。对话级 ledger 持久化 ✅（`website_style_confirmed` journal fact + `turn_paused.website_style` 再水化；memory 仅热缓存）。**P1b 营销 section catalog ✅**（`runtime/runs/website_catalog/marketing/` 10 壳；playbook 注入空壳正文 + `_shared.css` + CONTRACT 起步表；骨架豁免 DESIGN placeholder；禁令复述不误伤 lorem；扫描不做壳硬闸）。**工具台 dense（`tool_dense`）+ `build_toolshed` ✅**：独立 playbook **`build_toolshed`**（同五波；pack `tool_dense` + anti-slop `domain=tool`；首批 8 壳）；**`build_website` 营销-only**（v1 不开 pack 槽）；CEO 路由 = 落地页/官网/营销 → `build_website`，控制台/后台/工具台/SaaS admin → `build_toolshed`（结构化 id）；手写旁路硬拒覆盖两类意图（`is_site_build_intent`）。→ 建站前端质量 P1 定案（详细提案不在公开仓 / 维护者本地）。**P1c 截图·VLM critic ✅**（`deliverable.visual_critic` + `website_visual_critic.py`；复用 `VisionReader` / browser session `set_content`+`set_viewport`；产物 `site/VISUAL_CRITIC.json`；无能力 → 未目验）。
- **playbook 扇出粒度与超限口径 ✅**：**不再静默截断丢弃**，按 slot 语义分三种——① `build_website` / `build_toolshed` sections **确定性分组**（`_adaptive_partition_slots`，不给 CEO 粒度旋钮）：N≤3 一比一；N≥4 相邻两段一组后再按 **`_BUILD_WEBSITE_SECTION_MAX_WIDTH=2`** 折叠（**不改**全局 `MAX_PLAYBOOK_FANOUT=6`，调研/compare 仍用 6）；② 覆盖面语义 slot（`research_report` angles、MLR lenses）超限**折叠合并**（`_fold_fanout_slots`；MLR 折叠只并尾部、保首透镜独占公共底料分工）；③ `compare_options` options 超 6 **显式拒绝**引导收敛短名单（一选项一评估员的客观性不可折叠）。①② 均产出 `playbook_note` 随 delegate 结果尾注回显 CEO / 用户。教训：GEO 官网传 8 段，「常见 FAQ」「底部 CTA」被无告警丢掉。→ 见代码: `runtime/runs/playbooks.py`。
- **MLR 落盘契约 ✅**：四透镜与汇总员均 `form=files`——完整报告写 `research/{透镜}透镜报告.md`、`research/汇总与命题卡.md`（handoff 结构化摘要照旧，落盘叠加不替代）。**命题保真**：用户原话机制注入汇总员任务；命题卡教法禁抬升 / 偏移辩题。目录约定见 [`双模式工作区.md`](/docs/02-架构/双模式工作区.md)。
- **透镜检索分工 ✅**：四透镜检索去重靠任务书级**静态分工**（`playbooks.py::_lens_retrieval_division`）——首透镜兼任公共底料负责人（查全时间线 / 主体 / 概况），其余透镜简要确认、预算专攻本透镜独有缺口；并行结构未动。**路由钉子**：CEO 常驻核心钉「对抗入口·按意图分流」（点名开辩 → `debate`；调研 → MLR），防路由被垂直 Skill 正文锁死（教训见 [`工具与能力系统.md` §二·摘要正文漂移](/docs/03-AI核心/工具与能力系统.md)）。
- **单源不漂移**：schema 的 enum / 槽位说明 + `team_orchestration_advanced` skill 清单都从注册表**单源生成**。
- **防僵化绊线**：只固化高频形状，不做万能模板引擎；要分支 / 条件 / 每次结构都不同 = 照常手写 `tasks`。
- **教法口径（对照学形状）✅**：playbook listing 嵌进 skill 时是**形状词汇的可实例化示例**——对照学形状，勿「是就直接套」；形态贴合时可设 `playbook` + `playbook_args` 生成骨架（与手写 `tasks` 二选一），否则按词汇手写。建站「必须」保留；功能/MLR **不**文案强推「优先」。**成篇调研软偏好（非硬锁）**：要落盘的中篇实务/研究报告且尚需 ≥2 可并行取证角 → 常驻路由 + `team_orchestration_advanced` / `long_form_writing` 划界【宜】`research_report`（禁一人自搜+成文；材料已齐扩写仍单写手）。自检：换个主题，形状还一模一样吗？还一样就错了。

→ 见代码：`runtime/skills.py`（对照学形状口径）、`runtime/runs/playbooks.py`、`runtime/delegate/playbook_declaration.py`、`tools/builtin/delegate/`。

---

## 二、关键字段设计决策

`delegate` 每个 task 的字段语义见文首代码指针。下表只记录设计理由。

### 2.1 worker 执行参数档 — 单一档位（无模型档位选择）

CEO `delegate` **不声明模型档位**（原 `model_preference{fast,strong}` 与 per-task 思考强度 `reasoning_effort` 已整体删除）。所有 worker 走同一 `agent` 场景画像，**回合预算统一为单一上限**（沿用原 `strong` 值 28）——CEO 既不选模型、也不给单个 worker 调「力度旋钮」。

设计理由：① 解耦委派与具体模型名，模型更新不改委派逻辑；② **力度差异由委派协作结构表达**——需要更强推理 / 更高质量时，CEO 用「拆分子任务、加复审节点、`replan` 迭代」等**协作结构**去表达，而非给一个 worker 升档。旧两档（`fast`/`strong`）+ `reasoning_effort` 从 MVP 起即 inert、从不下发 LLM，保留只增认知负担与假象，故整体移除。

**用户模型组合（主 + 可选 Worker / 后台）** — 默认仍「全队一颗」：CEO、辩论辩手共用该 turn 解析出的**主模型**；组合的 Worker 槽（空 = 跟随主模型）仅在组队时给队员换模型。用户在「设置·模型配置」维护**多服务商列表**与**模型组合**（✅ 2026-07-25：`llm_model_profiles`；账号 `default_model_profile_id`；会话活引用 `model_profile_id`）。`LlmModelProfileService.expand` → `resolve_conversation_model_selection` / `resolve_turn_model`（`llm/resolve.py`）得到主模型 `(model, origin, provider_id)`；目录与授权闸见 [平台LLM接入 §二](/docs/05-平台与运维/平台LLM接入.md)。`resolve_turn_profiles` 把主模型放进 `TurnProfiles.model`；有效且与主模型不同的 Worker 槽写入 `model_overrides["agent"]`（跨服务商时另带 `agent_provider_id`；sidecar 在 `cost_role=member` 时按 Worker 重解析）。辩论经 `cost_role=arena` + 注入 turn main，**不跟 Worker**。**会话选择器只切组合**；不做 per-worker / `delegate` 选档、不做输入框双 picker。场景 profile（`ProfileParams`）只按场景分化执行参数（温度/轮数），**不含模型名**，勿与模型组合混名。

- **被否决：质量档矩阵**（`经济档`/`高质量档`、CEO vs worker 分选 Flash/Pro）——多数用户只想「配一套能用的模型」；质量档解析链与相关列**均已永久移除**。✅ 模型组合的 Worker/后台槽是组合内可选槽（默认跟随、会话不双 picker），不是质量档矩阵回归。
- **MVP 约束**：不下发额外推理强度参数，`thinking` 走各家默认行为；⏳ per-provider 推理字段适配、原生 Claude/Gemini provider 见远期。
- **`supports_tools` soft gate**：BYOK probe 判定「端点是否接受工具调用」，三态持久化（`True` / `False` / `None`）——`tool_calls` 回包 = 强证据 `True`；可判定为拒绝 tools 参数的 4xx = `False`；其余一律 `None`，**不再把未知冒充 False**。结果作 UI 提示 + preflight warning，**不做 hard 400**。
- **后台 one-shot**（memory / title / compaction）：**平台优先**（✅ 2026-07-25，见 [平台LLM接入 §二](/docs/05-平台与运维/平台LLM接入.md)）；平台不可用才回落组合 `background` 槽（空 = 跟随主模型）。执行参数照场景 profile 降 temperature / max_tokens。与 Worker 槽正交。
- **Provider 路由保留、MVP 不暴露**：`ProviderRouter` 的 `provider/model` 前缀路由供 eval / ⏳ 辩论多模型辩手；MVP 辩论统一用户主模型（不跟 Worker 槽）。

→ 见代码：`llm/model_profiles.py`、`llm/resolve.py`、`llm/provider_service.py`、`api/routes/llm_model_profiles.py`；前端见 [`../04-前端/前端UX设计.md` §十三](/docs/04-前端/前端UX设计.md)、[`../04-前端/前端成本呈现.md` §7.4](/docs/04-前端/前端成本呈现.md)。

### 2.2 `depends_on` — 依赖关系（并行/串行的唯一开关）

执行形状是**数据不是模式**：

- `depends_on: []` → 可立即启动（与其他无依赖步骤并行）
- `depends_on: ["a"]` → 等 a 完成后启动
- `depends_on: ["a","b"]` → 等两个都完成

调度器解析依赖自动确定并行度，无需 CEO 显式声明「这是并行的」。

### 2.3 `result_handling` — 上游产物保真度

下游节点注入上游 `RunState.content` 时的裁剪策略：

| 值 | 含义 | 何时使用 |
|---|---|---|
| `pass_through` | 全文（带共享预算） | 分析/检索→写作链路，须保留金额、法条编号等细节（默认取向） |
| `summarize` | 摘要 | 大扇入合成省 token 的场景 |

> **默认偏全文**：「一律摘要」会丢失关键信息。执行形状由 `depends_on` 自然落定，无需离散计划类型。

> **保真度预算 ✅**：每下游 worker 一份总预算，多依赖水填充；超额首尾保留。→ 见代码: `runtime/runs/fidelity.py`
>
> **递指针不递全文 ✅**：上游已落盘则递路径清单，不占 pass_through 预算。
>
> **CEO 综述同款保真度 ✅**：落盘递指针 + 纯文本共享预算；**否决整段盲截**；**刻意不按 `result_handling`**。→ 见代码: `runtime/delegate/ceo_format.py`
>
> **工作区产物清单 ✅**：开局注入队友产物 + 既有文件（预算封顶）。
>
> **并行写隔离 / C3 较强文件归属 ✅**：协调会话级归属表（**具体文件** `deliverable.artifacts` 声明即占，完成后仍占；与批次 `WriteCoordinator` 统一一本账）；**`artifact_dir` / 目录前缀 / 通配只做验收覆盖、不进归属键**——同批可共享案卷目录。写时互斥覆盖 `file_write` / `file_append` / `str_replace` / `write_section`（及 delete/move）；祖先交接 / `replaces_run_id` / `continue_from_run_id` / `force` 可移交。`code_execute` 写回本期不硬拦。回滚开关 `engine_file_ownership_v2=false` → 仅未完成启发式 + 批内 write/append claim。非协调批仍为批内守卫。→ 见代码: `workspace/write_claims.py`、`runtime/coordination/append_guard.py`、`runtime/runs/artifact_dir.py`
>
> **覆盖写完整性 ✅**：成篇非空目标（≥约 400 字）的 `file_write` 整文件覆盖 → **硬拒绝**并引导 `str_replace` /（骨架上的）`file_append`；不足阈值的短文件仍可覆盖（保留完整性软警示）。
>
> **Artifact-first Writing ✅**：中等单篇默认一次 `file_write`；写/append 回执 = artifact manifest（作者验真，禁自产物 body `file_read`；下游/CEO 可读他人落盘）；本 run 已成篇 prose 的同 path 禁再 `file_append`；超长仅「短骨架 → 按节填空」。→ 见代码: `tools/builtin/file_ops.py`、Skill `long_form_writing`

### 2.4 嵌套委派（一层，默认开）✅ 已落地

**委派默认开、无 per-node 开关**：任何 `depth < MAX_DELEGATION_DEPTH` 的 worker 启动即获 `delegate` + `replan`，拥有绑定到**自身为 captain** 的一层子队拆分权，看到子成员产出后自行整合。「能不能带队」纯由树位置（`depth`）决定，不再有 `can_delegate` 字段。

- **硬上限**：`depth ≤ 2`；单 lead 扇出 ≤4；树级并发预算分而不乘。姿态二选一靠 prompt（不硬拦）。账目按树回滚。

> 设计理由：一层深度 + 扇出上限 = 表达力 vs 可控。**能力默认给、上限硬卡**。**否决·`can_delegate` opt-in**（曾落地后撤销）；**仍否决**无界递归与硬拦双路径。

> **lead 自主 replan 子树 ✅**：与根一致经 `LeadSubteam`；**否决·A 约束式**禁 lead 用边界。→ 见代码: `tools/builtin/delegate/nesting.py`

### 2.5 `RunSpec.tools` — worker 工具集（内部装配载体，**缺省 = 全量**）✅

worker 的可用工具**不由 CEO 手填**：`delegate` / `replan` 曾有的 task 级 `tools` 参数**已移除**（该入口无提示引导、实践几乎不用，且真正的工具收窄本就由结构化信号自动完成）。`RunSpec.tools` 保留为**引擎内部装配载体**：缺省 `None` = 提供全部团队工具；仅被内部写入者收窄时才是子集。

- **谁写它（内部）**：① 检索预算（`retrieval_budget=0` → 从白名单剥离 `web_search`/`read_url`，见 §2.6.1）；② 系统 playbook（如 `organize_folder` 给文件整理助手写死 file-only 集）。**工具面主收窄靠结构化信号**——`deliverable.form=prose` 由 registry 直接撤写文件工具、非协作批次撤便签工具、云沙箱无执行类工具（能力闸），均不经 `tools` 白名单。
- **缺省即全量（fail-safe）**：`builder._tools` **永不产出 `[]`**——省略 / 只含未知名 → `None`（引擎读作「不限制、提供全部工具」）；非空且经 allow-list 过滤后仍非空 → 该子集。**否决「缺省 = 空列表」**：引擎把空 allow-list 读作 `tool_choice="none"`（不提供任何工具），会把本该 `file_write` 落盘的 worker 逼成纯文本 Agent——吐文件正文进聊天、工作区空空、CEO 据「文件产出清单为空」误报成功。安全默认必须是「有能力」。
- **续派一致**：`RunSpec.tools` 落盘为 `list | None`，缺省序列化为 `null`，带现场续派（续写）唤回时还原成「不限制」而非「无工具」。

> 设计理由：worker 能不能干活属正确性、工具收窄属优化，故安全默认必须是「有能力」。**被否决①**：要求 CEO 必填 `tools`（依赖 LLM 自觉、脆弱，正是此前 worker 静默不落盘的翻车点）。**被否决②（原「CEO 可选手填收窄」已移除）**：保留 CEO 手填 `tools` opt-in 最小权限——无提示引导、CEO 基本不用，且 `form` / `retrieval_budget` 已覆盖真实收窄需求，故撤除该手填入口、`tools` 降为纯内部载体。→ 见代码：`runtime/runs/builder.py` `_tools`、`runtime/runs/types.py` `RunSpec.tools`、`runtime/runs/retrieval_budget.py`、`runtime/runs/playbooks.py`。

### 2.6 `completion_criteria` — worker 完工判据（省略不强制；绑定性禁止文案推断，误放 task 层自动提升）✅

批次「怎样算干完」的验收契约，档位：`files_written`（有 worker 产物落盘）/ `code_verified`（须真跑通——校验确有 `code_execute` / `test_run` 成功记录）/ `custom`（描述性，机械校验不了即报缺口）。

- **省略 = 不强制 + 仅结构化补全（废除文案推断）✅**：CEO 未显式声明时默认**不启用批次验收**；仅当任一 worker 声明 `deliverable.artifacts` 或 `form=files` 时自动解析为 `files_written`（结构化信号；路径级对账另由 per-worker 契约门执行）。task 含「运行 / 打开 / 安装 / 启动」类语义**不再**绑定 `code_verified`——真运行类任务须由 CEO **显式**声明（skill / CEO 提示词已升为硬要求）。「直接打开软件」类：无本机打开能力 → CEO 终向须 `ask_user`（eval `delegate_run_app` 现为 `NotDelegated` 棘轮，禁假委派冒充已打开）；有 `local_open` 时才可 `delegate` 并显式 `code_verified`——由回合**能力策略**收口（见下），不再靠「必须委派」一条金标硬拧。非绑定软警告（运行 / 二进制产物启发）仍随 delegate 结果返回。delegate 工具结果**始终回显** resolved 验收（含「本批验收：未启用」），CEO 当轮可见可改。**为何废除文案推断**（2026-07-18 提案 B1）：静态产物文案天然带「打开页面」类字眼，误推后 unmet → 无限重派；「打开软件」路径 A 改由显式声明 + 能力策略兜住。**为何不默认强制**：写文档 / 纯讨论类本无落盘或跑通语义；落盘要求由 per-worker `deliverable` 承载。提案正文与实测依据见 git 历史（检索与交付约束前置提案）。
- **验收标准注入 worker（B2）✅**：resolved criteria 写入持**执行类工具**（`tools is None` 或 allow-list 含 `code_execute` / `test_run` / `terminal`）且 `form=files` 的节点的「交付物规格」块——避免调研 / prose 全员冗余跑验证。禁止按 role 字符串圈定。
- **误放 task 层自动提升（hoist）+ 同缺口收敛**：正式契约位置在 delegate **顶层**（与 tasks 同级）；顶层缺失且单 task / 多 task 值一致 → 自动提升并打 `delegate.completion_criteria_hoisted`；多 task 值冲突 → 参数校验报错。验收 unmet 的 gap 消息**必标 criteria 来源**（显式 / 结构化）；同一委派**连续 2 次相同缺口** → 升级收口。→ 见代码：`completion.py` `hoist_task_completion_criteria` / `resolve_completion_with_source` / `format_completion_gap_message` / `format_resolved_acceptance_echo`。
- **评估口径（vacuous pass 已修）**：criteria 针对**全部 COMPLETED worker** 的真实信号评估——纯落盘、纯 handoff 的空正文完成态同样计入；无任何证据 = 缺口，绝不空过。
- **收敛强制收尾与缺口上报**：治理 `convergence_finalize` 仍禁写文件（只读收口），但收尾后契约缺口以 per-worker gaps 段写入 delegate 汇总。
- **对治「写了但跑不起来」**：路径 A·工作区内验收靠**显式** `code_verified` + 收尾校验（不再文案推断）；路径 B·本机 OS 启动 / 打开软件走 sidecar / Client Tools（无 `local_open` 时先 `ask_user`，勿直答冒充已打开），见 [`双模式工作区.md` §十](/docs/02-架构/双模式工作区.md)、[`安全权限与治理.md` §三](/docs/05-平台与运维/安全权限与治理.md)。
- **CEO 回合能力策略（跑 / 打开验证 / 贴码写回 / 打开软件）✅**：窄意图 × 本回合能力（`workspace_context`：`code_execute` / browser / `local_open`）由引擎硬收终向——有能力 → 只许 `delegate`（跑修可叠显式 `code_verified`）；缺能力或缺可验产物路径 → 只许 `ask_user`；**贴码写回**恒 `delegate`（空仓也须落盘，禁口述修复当直答）。禁止用翻目录 / 读文件冒充已跑 / 已验。→ 见代码：`runtime/runs/exec_verify.py`、`runtime/engine/governance.py`
- **委派前能力闸 ✅**：**resolved `code_verified`**（显式声明，与收尾验收共用同一 resolver；文案启发不进硬闸）撞上「本回合无执行环境」→ `delegate` **硬拒绝**，给三条出路（`bind_local_folder` / 改 `files_written` / 先 `ask_user`）。剩余软警告：resolved 非 `code_verified` 但文案含运行 / 二进制产物暗示 → 工具结果尾部注入不拦截（宁漏不错杀）。→ 见代码：`completion.py` `validate_execution_capability` / `execution_capability_warning`。
- **交付底线前置（finish_guard B3 一期）✅**：共享基座提示词含 `<delivery_baseline>`（围栏须闭合、`#rN` 须在台账内）；命中频率靠既有 `engine.finish_guard_rework` 日志可统计。自动规范化 / 新 reset reason 属二期，本批不做。
- **交付状态结构化（`delivery_status` 事件）✅**：批次收尾把已有信号汇成面向用户的结构化交付对账——`state` + 已交付文件 + 缺口 + 待用户操作。DURABLE、同 `execution_id` 保最新；纯 prose 成功批次无声。→ 见代码：`runtime/runs/cutoff.py`、`runtime/delegate/delivery_status.py`、conformance 向量 `multi_agent_delivery_status_partial`。
- → 见代码：`runtime/delegate/completion.py`、`tools/builtin/delegate/`、`runtime/runs/executor_context.py`、`runtime/resolve/prompt.py`。

### 2.6.1 `retrieval_budget` — 检索预算（契约字段 + 结构化默认）✅

task 级可选字段：该 worker 本 run 的检索额度（`web_search` / `read_url`）。**结构化默认**（禁止按 role 字符串判定；与 worker token 硬顶同构——统一单值 + 硬例外，**不做**批级共享池 / 按 worker 数缩放）：任意非 `form=prose`、且 CEO 未显式声明 → **14**（开发期无真实产线数据，假设统一阀）；`form=prose` → **0** 且**不装配检索工具**；CEO / schema 显式 `retrieval_budget` 恒优先（含显式 0）；续派提额路径不动。`is_research_root` 谓词可留作别用，**不再**参与检索默认分档。enforce 在 engine 工具执行层（缓存命中与被拒调用不计费；与 `LoopController` / `team_gate` **正交**，禁止挂接）。预算用尽 → 结构化反馈「基于台账现有证据交付 + 交接标注检索缺口」，缺口经契约缺口块上浮，CEO 以 `continue_from_run_id` 续派显式提额——**无 mid-run 追加通道**（`escalate` 语义不扩，`kind=resource` 属后置另案 → 远期规划 §三·检索与交付后置项（详细提案不在公开仓 / 维护者本地））。**同轮超订缓解**：剩余槽位 ≤2 且未耗尽时，引擎经既有 reflection 注入一次性告知剩余额度（`engine.retrieval_budget_critical`），减少当轮 fan-out 超订被挡回浪费槽位；耗尽仍走既有 wind_down。设计理由与取舍见 git 历史（检索与交付约束前置提案 §三 A1）。→ 见代码：`runtime/runs/retrieval_budget.py`、`tools/builtin/delegate/schema.py`、`runtime/engine/tool_exec.py`、`runtime/engine/loop.py`。

### 2.7 `continue_from_run_id` — 带现场续派（同人接续）✅

task 级可选字段：声明该任务由目标 run 的作者**带完整 ReAct 现场（transcript）**接着干——改自己的稿或接强相关新任务（同一动作，task 内容区分；独立工具 `revise` 已退役）。续派任务享有 delegate 全套能力（`depends_on` / `deliverable` / `objective`…），可与依赖同批混排（依赖同批完成的 run 也可续，登记时机 = 单 run 完成即登记）。强相关接续 → 续派；换角色 / 救失败稿 / 合并多产物 / 独立新任务 → 冷委派（防上下文污染），必要时以 `replaces_run_id` 标接手。miss / 超限 / 目标进行中 / 自指 → **明确拒绝**该项并提示回落冷委派，不静默降级。机制、留人存储与约束边界的权威文档见 [`多轮编排与同人续派.md`](/docs/03-AI核心/多轮编排与同人续派.md)。→ 见代码：`tools/builtin/delegate/schema.py`、`runtime/delegate/continuation.py`。

---

## 三、失败处理

| 失败场景 | 处理策略 |
|---------|---------|
| `delegate` 参数非法（无环校验失败、工具未注册、档位非法等） | `build_run_plan` 收集 `errors` 非终态返回 CEO，CEO 改参数重试 |
| 单个 worker 失败 / 被取消 | 先按节点 `on_failure` 处理（`retry` 退避重跑 / `abort` 停波）；下游按**宽松扇入**默认放行——≥1 个上游成功即照跑、缺席上游在任务输入中标注（取消≠失败；防单上游取消级联拖掉汇总员），任务声明 `require_upstream=true` 才恢复「任一取消/失败即级联跳过」。零成功上游时跳过，补派设 `replaces_run_id` 改写下游依赖并复活。单 worker 失败不必拖垮整 DAG（见 [`执行引擎架构设计.md` §一](/docs/03-AI核心/执行引擎架构设计.md)） |
| CEO 判断无需团队 | 不调 `delegate`，直接作答（等价单 Agent，安全兜底） |

---

## 四、开场引导：`ask_user` 开工提案卡 ✅ 已落地

> 开场引导是 `ask_user`（CEO 唯一的「向用户发问」原语）的一种**内容形态**，不是独立工具。→ 见代码：`tools/builtin/ask_user/`、前端 `CheckpointCard.tsx`。

对「**能做、但用户没说全**」的产出类请求（做网站 / 应用 / 海报 / 文档…，且用合理默认就能开工），CEO 不甩一堵澄清问题墙、也不闷头开干，而是调 `ask_user` 开一张**开工提案卡**开场：用自己的口吻复述目标（`message`）、摊开起步计划与少数高杠杆决策，让想省事的人一键开做、想管的人就地调整。**建站 / 落地页风格双闸 ✅**：kickoff `ask_user` **强制非空** `style_options`（id=`s0/s1…`，否则拒调）；resume 显式 `style_id`（优先）或 `selected` 合法 `sN` **结构化记账**（禁散文 note 独过闸）；`build_website` 无记账则拒调（`AutonomyPolicy.full_auto` 仅建站风格确认窄豁免 → 落默认风格进记账与 DESIGN）。挂点是 `ask_user`（非 `team_preview` / 非强制 `proposal_pick`）。桌面 + 手机同 resume 契约。→ 见代码: `runtime/runs/website_style.py`；ledger 持久化 ✅ / P1b catalog ✅ / **P1c visual critic ✅** → 建站前端质量 P1 定案（详细提案不在公开仓 / 维护者本地）。

### 决策按「影响力」分档（核心设计）

分档依据是**影响力**而非「是不是技术」——技术决策也可能高杠杆（要不要响应式 / 双语 / 带后台）：

| 档 | 字段 | 语义 | 上限 |
|---|---|---|---|
| 起步计划（安静默认） | `assumptions` | 影响小、可逆、用户多半不关心的决策（框架 / 目录 / 部署 / 命名）。CEO 替用户定好，以「项 + 值」**只读**陈列让其知情（v1 不可改，靠备注框兜底） | 10 |
| 重点问题（主动征询） | `questions` | 真正值得用户拍板的少数高杠杆决策。**每个都预填 `default`**——即便问满上限，想省事的用户一键全默认通过，不退化回问题墙。`kind=choice`（单 / 多选）或 `text`（填一句） | 5 个（对齐 Cursor 2.1 的 3–5）；每问选项 ≤6 |
| 风格基调 | `style_options` | **仅视觉类产物**（网站 / 海报 / 幻灯）给的风格预设供选基调；非视觉类省略 | 6 |

> 判准：决策选错会不会让用户明显不满、甚至推倒重来？会 → 提为重点问题；不会且有稳妥默认 → 放进起步计划默认掉。拿不准时**中性**：代价高 → 放进 questions（预填 default，一键可过）；代价低 → assumptions 写明。不偏「尽量少问 / 宁可默认」，也不偏「凡事先问」。CEO 只供语义内容（标签 / 选项 / 默认值），工具负责分配稳定 id 并 cap 尺寸，防失控 prompt 撑爆卡片。

### 统一机制：开场与途中共用 `ask_user`；默认挂起、可选非阻塞（核心设计）

`ask_user` 是 CEO **唯一**的发问原语：开场引导与执行途中的高代价岔路用**同一张卡、同一套机制**，沿**内容形态**（开场味 / 途中味）与**是否阻塞**（`blocking`，默认 true）两个正交维度自适应——

| | 开场味 | 途中味 |
|---|---|---|
| 时机 | 回合开场，请求能做但没说全 | 执行途中撞上高代价岔路 |
| 内容 | `message` 复述目标 + `assumptions` 起步计划 + ≤5 预填 `default` 的 `questions` + 视觉类 `style_options` | `message` 说清现状 + 通常一个无 `default` 的 `questions`（就是要用户选） |
| 卡片语气 | 中性灰壳 + 蓝主 CTA（V2 Brief+Choose，选项选中态蓝） | 中性灰壳灰选项 + 蓝主 CTA（原「琥珀待裁决」已废除，2026-07 拍板：拍板类卡片不用琥珀） |
| 回合 | 默认**挂起**待回值；用户选「停止」结束本回合（也可 `blocking=false` 非阻塞，见下） | 同左 |

**为什么不让模型选「开场工具 vs 途中工具」**：开场 vs 途中是**内容形态**之别，不是机制之别——该结束还是该挂起是**运行时**的职责。挂起 + 恢复是通用情形（保留在途上下文——委派结果、已读文件），开场只是「在途上下文很少」的特例、以可忽略成本被它涵盖。模型只需决定**要不要发问**（克制），不必判别**哪种发问**。

**阻塞与否（`blocking`）则归模型——与上面不矛盾**：开场/途中是伪选择（同一机制的内容差异），而「这个岔路值不值得冻住用户」是**真·语义判断**，只有模型知道自己手上的默认有多稳、岔路猜错代价多大，运行时无从代判。故新增一个正交维度交给模型：默认 `blocking=true`（挂起等答复，用于高风险 / 不可逆 / 无合理默认）；`blocking=false` 时**抛出问题但不挂起**——模型必须在 `assumptions` 或某 `question.default` 写明将先采用的默认（否则该调用被拒，防"非阻塞=偷偷瞎猜"），随即按默认续跑把回合做完，用户回复作为新消息在后续轮次并入。这是 worker `escalate`「问而不停」在 CEO↔用户层的对偶。

阻塞检查点走**挂起即收口**：到点落帧收口回合（`FinishReason.PAUSED`），答复经单一冷路 `POST …/messages/{id}/resume` 续跑（不再 `POST …/interactions` 原地解析）；挂起/续跑契约见 [`执行引擎架构设计.md` §检查点决策语义 / §暂停与恢复](/docs/03-AI核心/执行引擎架构设计.md)。前端卡片见 [`../04-前端/前端UX设计.md`](/docs/04-前端/前端UX设计.md)。

**何时不用 `ask_user`**：简单问答 / 闲聊 / 检索直答——直接答；需求已说全、无值得确认的决策——直接 `delegate` 开干；连意图都不可解（目标都复述不出）——先用一句普通文字问清意图，而不是出卡。

> **被否决**：① **开场即甩问题墙**（故每个重点问题强制预填默认）。② **开场与途中做成两个工具（`kickoff` + `ask_user`）**——统一为单工具 `ask_user`，阻塞与否由 `blocking` 正交维度表达。

---

## 五、检查点与团队预审

**产品触发**：CEO 在关键岔路调 `ask_user`（运行时自决）；DAG 计划在 step 标 `checkpoint_after` 时由调度器波间挂起 `plan_review`。**边界**：`ask_user` = CEO 工具效应；`checkpoint_after` = 计划期声明的结构挂起——语义、2b 续跑、事件契约见 [`执行引擎架构设计.md` §检查点决策语义 / §暂停与恢复](/docs/03-AI核心/执行引擎架构设计.md)。

**CEO 评审前置 ✅**：`checkpoint_after` 波完成 → durable `plan_review` 暂停前，引擎强制主 Agent 一轮把关（读本波落盘 / handoff），把关摘要（`conclusion` + `risks` + `suggestions` + `source`）写入 `plan_review_required.ceo_review`（拍板卡展示；继续时 llm 把关压缩注入 `gate_notes`）。LLM 不可用时回落确定性摘要（`source=deterministic`，默认不下发），不阻断暂停。

**部分并行 ✅**：`delegate.parallelism` ∈ `conservative`（默认）/ `balanced` / `aggressive`。默认严格按 `depends_on`；`balanced` 在检查点后线性链上保留第一跳、中段扇出再汇合，避免构建流水线被全串行锁死。→ 见代码：`runtime/delegate/parallelism.py`。

**团队开工卡（编排层统一 ✅）**：顶层编排原语（``delegate`` / ``debate``）在 fan-out /
主持人循环启动前，经编排层公共 kickoff gate 决定是否挂起 `team_preview` 开工卡（事件对
`team_preview_required` / `team_preview_resolved`；payload 带 ``primitive`` 判别）。
触发规则只存在一份（`runtime/kickoff`）。

- **delegate**：`run_plan` 已发出、**首波尚未启动**时，若计划需预审（≥2 worker **或** 含辩论标记）
  **或**本地模式下需能力授权（`AutonomyPolicy.first_grant`），则挂卡。卡片展示角色 / 任务摘要 /
  依赖 / 是否辩论 **与** 将授权的能力范围（GRANTABLE 白名单）；动作：**授权并开工**（可带嘱咐；
  非空备注 ≡ 原 adjust，steer 注入全体未跑队员）/ **停止**（`per_call` 与独立「调整」入口已撤，
  枚举保留供历史渲染）。
- **debate**：顶层调用一律弹计划卡（辩题 / 各方立场 / 轮次预算）；能力半边对只读辩手为 False。
  动作：**授权开赛**（可带开赛嘱咐；非空备注 → 首轮全场用户插话，不覆写 motion）/ **停止**
  （独立「调整」入口已撤——旧「调整=改写辩题、立场保留」与 CEO 拟题对齐冲突且与 delegate 嘱咐分裂；
  换辩题 = 停止后对 CEO 重说；`ADJUST` 枚举保留，历史/API 按 CONTINUE+note 同语义）。
  暂停点在 `debate.started` 之前。原条件第三键 `research_first` 已退役（见下）。
- **`research_first` 键已退役 ✅（2026-07-21，随庭前取证内化）**：开工卡不再提供 / 推荐该键（`offer_research_first` / `research_first_recommended` 恒 False；历史已决卡渲染保留）。退役理由：实测自然路径闸门失效——推荐启发式未亮、用户秒点开赛；取证改为辩论固有「庭前取证」阶段，开工卡回归授权预览 → [辩论编排 §二之二](/docs/03-AI核心/辩论编排设计.md)。阶段推进卡的 `research_first` decision **保留**（调研线回灌）。→ 见代码：`runtime/kickoff/research_first.py`。
- 续跑复用既有 durable Interaction / `POST …/resume` 管线。原独立热路 `delegation_authorization` 卡已并入。

**阶段推进卡（`stage_card` · 幕间衔接 ✅）**：幕1（MLR）收尾产出合规命题卡时，芯片升级为可操作耐久交互（kind=`stage_card`，跨回合 pending；幕1 **正常收尾不挂起**——语义是「幕1 已交付、下一幕待授权」，**否决**幕1 内冷挂起）。消灭「芯片 → CEO 转述 → team_preview」三段重复：

- **一步制**：点「按此开辩」= 机制直起辩论（`skip_kickoff`、`authorized_by=stage_card`），**不再弹开工卡**；无命题卡的单独辩论仍走 `team_preview`。**否决**二步制。
- **decision 二值**：`start_debate`（可带 `motion_override` / `note`）/ `research_first`（回灌 CEO，v1 不机制直起 MLR）。
- **失效 / 结算（决策）**：发新消息**不立即** orphan——pending 时 CEO 调 `debate` = 消费最近卡；回合收尾既未辩也未起 MLR 才 orphan。**否决**「发消息即 orphan」。消卡边界 = `debate.started` 开跑即消（非整场辩完）。
- **配套**：有合规命题卡时停发确定性「开辩」followup；CEO 教法禁口头征求开辩同意、禁本回合自调 debate。

→ 见代码：`runtime/kickoff/stage_card.py`。

**跳过（完成态降噪）**：单 worker + `finalize` 直出且无需能力授权；同 CEO 回合内已有阻塞 `ask_user` 且用户已提交确认、且无需能力授权时跳过。**批含 `checkpoint_after` 节点时计划预览半边让位**（主拍板四选一通则：该批的主拍板是波间提纲卡，开工卡不再叠计划确认；能力授权半边照原规则独立判定——安全刚需不算主拍板）。`AutonomyPolicy.full_auto` **放行计划半边与能力半边**（两原语都不弹开工卡，能力静默授权）。嵌套 `depth>0` / `light` / 续跑（`seed_completed`）不挂。

**与近邻边界**：开工卡 = 开干前否决权 + 能力授权（fan-out 前）；`plan_review` = 波间结构化挂起（`checkpoint_after` 后）；`ask_user` = CEO 主动拍板。勿混用。

**专用拍板卡（`ask_user card` 参数 ✅）**：两类高频主拍板复用 `ask_user` 冷路（不新增交互 kind），显式 `card` 声明并经结构校验后写进 `checkpoint_required.intent`（四值：`kickoff` / `decision` / `proposal_pick` / `risk_ack`）——**方案挑选卡** `card="proposal_pick"`（发散挑选型：恰 1 个 choice 问题、单选、options 2–6 个候选方案，`recommended` 标最看好项；用户挑中后 `continue_from_run_id` 唤回原作者深化）；**风险确认卡** `card="risk_ack"`（审查诊断型：恰 1 问、`multiple=true`、options 1–10 条风险项，label 约定以严重度前缀开头；勾选项转定向修订委派）。校验不合规拒绝并回引导文案；非阻塞路径禁用 card。**主拍板四选一通则**（开工提案 / 提纲把关 / 方案挑选 / 风险确认，每任务恰好一张）在 CEO 提示词层执行。→ 见代码：`tools/builtin/ask_user/card.py`、`runtime/checkpoints.py`、`runtime/resolve/prompt.py`、`runtime/skills.py`。

**AutonomyPolicy 三档 ✅**：`always_ask` / `first_grant`（默认）/ `full_auto`——`full_auto` 跳过整张开工卡；`first_grant` / `always_ask` 能力半边语义不变；`plan_review` / checkpoint 不受此三档影响。→ 见 [安全权限与治理 §三](/docs/05-平台与运维/安全权限与治理.md)。

**§7.2 Preflight Audit（⏳ 远期）**：有界审计环 / 可编辑改 DAG / Agent 实体化绑定 / 设置项 opt-out **本批不做**——见 [`Agent协作模式.md` §7.2](/docs/03-AI核心/Agent协作模式.md)。

---

## 六、待定事项（Phase 2 及以后）

> 仅列**真残留**；已落地项已迁入各正文，不在此复述（落地即出表）。

| 议题 | 残留 |
|------|------|
| system prompt 内容调试 | 结构（身份+边界）/ 委派判据已落地于提示词管理者职责段（见 §核心定位 / §协调者工具边界、`resolve/prompt.py`）；剩内容调试——worker 角色模板、各系统 Skill 正文实测校准。〔注〕运行期 `delegation_nudge` 软护栏**未落地**——曾试，A/B 实测被无视且净负已移除（见 `loop_controller.py` 过度调查保险丝注释），委派改靠结构性边界决策 + 上述提示词护栏治理，与 [`执行引擎架构设计.md`（§被否决·运行期软护栏）](/docs/03-AI核心/执行引擎架构设计.md) 一致 |
| Agent 实体化 | Phase 1 worker 为内联角色（`agent_id == run_id`）；Phase 2 收敛到 `agent_id` + `AgentResolver` + 委派白名单 |
| 增量声明优化 | 批次预声明 + 跨波重排 + 晚绑定续跑均已落地（见 §一 `replan`）；剩更细粒度的增量重声明 |
| 交互原语回归 | `ask_user` / `plan_review` / `checkpoint_after` / 团队预审薄预览 `team_preview` 已落地（见 §四 / §五）；剩 §7.2 完整 Preflight Audit / 契约闸门 / 治理强制层（远期）⏳ |

---

## 未来优化方向

> 来源：已退役的规划文档「多Agent编排优化-参考Cursor-Multitask」。以下为经评估后暂缓的优化方向，留作未来参考。

### 暂缓项

| 方向 | 内容 | 重新评估时机 |
|---|---|---|
| finalize 单 worker 早释放 | CEO 委派后提前释放 LLM 上下文，worker 完成后再唤回 CEO 写综述 | 需状态落盘续跑能力成熟后 |
| 协调效率指标 | batch_metrics 中增加有效并行度、协调税率等观测指标 | 有真实用户流量后 |

### 已否决方案

| 方案 | 理由 |
|---|---|
| 替换 CEO 为纯路由器 | CEO 的精细规划能力是 AgentCore 核心壁垒（复杂任务的 DAG 编排 >> Cursor 的单 worker 路由） |
| 前置分类器 LLM | 已否决（每条消息付编排税，见编排器 §聊天优先） |
| Worker 直接通信 | 已否决（成本、不可观测，见协作模式 §二） |
| 取消 CEO 收尾综述 | CEO 的「一个声音」是产品核心体验 |
