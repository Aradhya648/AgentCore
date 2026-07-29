---
status: blueprint
code: apps/server/agentcore/
related:
  - docs/03-AI核心/运行时总览.md
  - docs/03-AI核心/执行引擎架构设计.md
  - docs/03-AI核心/检查点与开工卡.md
skip_if:
  - 只改检查点卡片 UX（读检查点与开工卡 / 前端UX）
---

# 编排器与 CEO 主 Agent

> **权威范围**：CEO 定位、职责边界、路由 / 团队形态 / 认知分工判据、关键字段语义、冷启动探索幕、`finalize` / `replan`。开场卡与检查点 → [检查点与开工卡](/docs/03-AI核心/检查点与开工卡.md)。实现细节 → 见代码: `apps/server/agentcore/runtime/`。

## 核心定位

编排能力归属会话型 **CEO 主 Agent**：唯一对话入口与声音，也是团队规划大脑。用户是老板；CEO 受雇掌管团队、对其负责——关键岔路请示、收尾汇报。确需团队时经 `delegate` 下达子任务，执行引擎调度 worker，CEO **用自己的声音**收尾。

CEO 是**管理者**（不是调查员）：主要持只读 / 检索工具，用于开工前轻量探路与收尾综述——**不**独自跑完整调查或亲手产出。本地且已装配 `terminal` 时，可对工作区长驻进程做启/停/读（纯启服轻量例外）。生产 / 变更一律 `delegate`；成规模广度调查（哪怕只读、最终只回一段话）也扇出并行调研 worker，回报精炼结论后由 CEO 综述。

底线：对用户呈现**一个 CEO 声音**；轻量 / 单点只读直答与纯启服（零编排开销）；组团 / 动手 / 广度调查按需触发。

### 职责边界

| ✅ CEO 做 | ❌ CEO 不做 |
|---|---|
| 与用户对话、来回澄清 | 持有写 / 改 / 删 / 移文件、Git 写入、跑代码等变更工具 |
| 轻量 / 单点只读直答（一两处文件 / 一条事实） | 亲自串行跑成规模广度调查 |
| 本地纯启服 / 重启 / 看长驻进程是否活着（`terminal`） | 用 `host_shell` 启长驻；改码 / 装依赖后仍假装自己动手 |
| 开工前只读探路；团队跑完写简短概览 | 为简单对话支付规划税 |
| 理解意图、拆任务、定角色与依赖（`depends_on`） | 复述各 worker 全文（细节由前端 run / 图视图展示） |

工具结构分界：`approval=NEVER` → CEO 持有；`GRANTABLE` schema → 仅 worker——**GRANTABLE 唯一例外**：本机 Host 的 `host_shell`（CEO+worker · `host` 轴授 · 禁 kickoff 静默授；L2/L3 仍仅 worker）。另：**本地 `terminal`** 亦 CEO 可持（schema `NEVER`，`start` 运行时升审批，与 `git` 写同姿）——纯启服 / 停 / 读，非改产物。自研编排（否决 LangGraph / CrewAI 等）：编排是核心壁垒，须完全掌控。聊天优先 + 按需编排（否决「编排器唯一入口」——每条消息付编排税）。

**档位取舍**：档 2.5 = 结构取档 2（CEO 只读 + 窄例外；否决档 1 全能 CEO、档 3 纯编排 CEO）+ 路由按「活的规模与结构」细化。档 1 污染上下文、弱化团队心智；档 3 给高频轻量只读 / 纯启服加委派税。

## 路由 / 团队 / 认知分工

发问优先：先判信息够不够，再判规模。产出类关键高杠杆决策用户没说全 → 立刻 `ask_user` 开工提案卡（勿先 consult）；信息齐了再判自己做 vs 交团队。

| 判据 | 结论 |
|---|---|
| **直答** | 单点确认、读已知少量文件、纯问答 / 闲聊、聊天里短文或短改写（未要求存文件）、开工前轻量探路；**本地纯启服 / 重启 / 看长驻是否活着**（`terminal`，勿为此派 `runtime_ready` 批） |
| **委派** | ① 实质交付物（代码 / 应用 / 要求落盘的成篇文字，哪怕一行）；② 成规模广度调查（横扫多来源、可拆多角度、需对比 / 辩论）——哪怕只读、最终只回一段话。单 worker 能胜任 → `finalize=true`；形状拿不准 → `consult_skill(team_orchestration_advanced)` |
| **团队形态** | 按活的自然缝拆、能少则少；可独立并行才多派；跨域合成流水线常见 1～2 人，勿默认每人一种专长。广度调查扇出并行调研，task 点明「回报精炼结论」。`result_handling` 只管上游→下游，**不**影响回到 CEO 的内容 |
| **认知分工** | 约束归 CEO、专业方案归专家；task 只写【目标·约束·验收】；`contract` 是验收契约非结构蓝图；审查类「重点关注」进 `seed_notes`(kind=heads_up)，勿写进 task 替 worker 作答 |

短文分界：未要求存文件 → 回复直写；明确落盘 → 派 1 人。CEO 绝不为省委派把整份代码贴进正文。

**部分材料明示范围**：用户附材料并收窄为本轮附件 / 工作区已有产物时，须先对照动手（缺口分析或改一版）；缺整仓只说明局限与单点缺件——禁止整轮只催源码。与打开本地项目正交（开项目=换工程面，非开工前置）。

**实证（一行）**：team 价值是同预算更便宜 / 更稳过硬性判据，非「更聪明」；跨域整合组队全面溃败 → 产品收窄为「按缝拆、跨域合成少派」。数据 → `apps/server/eval-out/`；跑法 → [本地开发 · evals](/docs/02-架构/本地开发.md)。

## `delegate` / `finalize` / `replan`

`delegate` 默认**非终态**：worker 跑完交回 CEO，CEO 写简短概览收尾（否决独立 SYNTHESIS 合稿节点）。图由 CEO 在 ReAct 循环里增量声明——非外部一次性 JSON 计划。

| 动作 | 语义 |
|---|---|
| 一次塞 N 个 task | 全景计划（一批声明完整分工） |
| 同回合再调 `delegate` | 并入**【同一张】**协作图（同 `execution_id`）；协调模式下不必等上一批完成 |
| 跨回合 `append_to_execution_id` | 复用旧图继续生长；默认新回合新建图，仅用户显式延续意图才追加；解析失败禁止静默新建 |
| 并行度 | 由节点 `depends_on` 数据声明（无依赖即同波并行），非靠模型并行 tool call |

**`finalize=true`**：单 worker 成功时 `HANDOFF` 直出为回合答复，省 CEO 合成轮；多 worker / 失败仍非终态、由 CEO 收尾。

**`replan`**（波边界续跑，与 `delegate` 正交）：含晚绑定（`bind_after_deps`）或队员 `escalate kind=scope` 时，调度器在决策边界让出；CEO 定稿 / 纠偏后续跑**同一张 DAG**。

| 参数 | 要点 |
|---|---|
| `binds` | 据上游产出把占位节点定稿（role / task / objective / deliverable） |
| `steers` | 给尚未运行的下游追加操舵；已完成步骤不可操舵 |
| `add` | 追加计划外新节点（拓扑校验；未知依赖 / 成环等整批拒绝） |
| `stop` | 未跑步骤 SKIPPED，已完成产出交回 CEO 收尾 |

`binds+steers+add` 先全量校验，任一非法 → 整批拒绝、暂停计划零改动。否决把 `delegate` 重载成「续跑旧计划」入口；带现场续派另见 [多轮编排与同人续派](/docs/03-AI核心/多轮编排与同人续派.md)。

协调模式（≥2 worker、根 CEO、非 finalize）：默认后台跑、CEO 继续 ReAct；`coordinate=false` / 单 worker / finalize / 含 `checkpoint_after` 仍阻塞。结构跟着证据走：调研成篇用 `depends_on` + `checkpoint_after` 把「定结构」摆到调研之后。委派后用团队产出写综述（提示强化，非硬禁只读）；根 CEO 探路成功的 list/read/grep 可摘要注入 worker 开局。worker 协作通道 → [Agent 协作模式](/docs/03-AI核心/Agent协作模式.md)。

收尾：先对账拼图边（4b：冲突 / 缺口 / 重复）→ 核验原始目标（4a：完工判定）→ 写概览；未达成就续派 / `replan`，别假装收工。`playbook`：建站/工具台/绿场软件(`build_app`)推荐具名形状（不再硬拒 `none`/手写）；其余自由组队（可选快捷形状）。**Agent/自动化意图**须先经开工卡交付形态三档（可运行自动化 / 控制台原型 / 仅方案）；仅「控制台原型」才允许 `build_toolshed` → [检查点与开工卡](/docs/03-AI核心/检查点与开工卡.md)。对抗性多视角另走 `debate` → [辩论编排设计](/docs/03-AI核心/辩论编排设计.md)。

提示词分层：常驻 = 路由脊柱 + 能力目录 + 短钩子；进阶 HOW 在系统 Skill，用时 `consult_skill`。同一条知识只在唯一所有者出现。

## 关键字段语义（摘要）

| 字段 / 概念 | 语义要点 |
|---|---|
| `depends_on` | 并行 / 串行的唯一开关；空 = 可立即并行；调度器据依赖定并行度 |
| `result_handling` | 上游→下游注入保真：`pass_through`（默认偏全文）/ `summarize`；**不**作用于 CEO 综述 |
| `complexity_hint` | `light`/`standard`：编排姿态（如 light 隐含 `coordination=none`），**不**映射 worker token/超时 |
| `coordination` | 便签墙档；缺省 `none`；权威 → [Agent 协作模式](/docs/03-AI核心/Agent协作模式.md) |
| `deliverable` | `requires_files` / `artifacts` = 落盘契约；否决悬空 `output_schema` |
| `completion_criteria` | 批次验收；省略不强制；文案推断已废除。`files_written` / `code_verified`（编译·测试·build，**默认走有界验证 `test_run`**）/ `runtime_ready`（terminal 长驻就绪）/ `graph_consistent`（`.ts/.tsx/.vue` import 图闭合；落盘此类文件时自动扫）互不混用；启动开发服务器用 `runtime_ready`；慢 build/tsc 勿塞 `code_execute` |
| `continue_from_run_id` | 带现场续派；权威 → [多轮编排与同人续派](/docs/03-AI核心/多轮编排与同人续派.md) |
| worker 模型 | CEO **不**选 per-task 模型档；力度用协作结构表达；用户侧「模型组合」可选 Worker 槽 |

嵌套委派：默认开一层（`depth≤2`），无 `can_delegate` 字段。worker 工具集缺省全量（内部装配；CEO 不手填 `tools`）。

## 冷启动探索幕

**触发（有项目 + 实质请求）**：

| 类 | 条件 | 挡当前请求？ |
|---|---|---|
| 挡请求 | 项目 `画像.md` 空 **或** `_memory_meta.explore_workspace_key` 与当前绑定不一致 **或** 用户点名「先了解 / 重新了解 / 刷新项目记忆」 | 是 → 先探索再继续原请求 |
| 指纹漂移 | 相对上次探索，**顶层树 + 关键清单指纹**已变 | **不挡**。一期：脏标记 + 软提示可点名刷新；二期：旁路静默更新（→ [记忆 · 探索触发](/docs/03-AI核心/Agent记忆与知识系统.md)） |

**挡请求流程**：注入 `<cold_start_explore>`（**仅**空仓建档 / 绑定已变两套；指纹**不**进此块）→ 先轻量探路（≤5 **轮**；同轮并行多工具只计 1 轮）→ `delegate`（`team_preview`）组调研队（**≥2 角并行**，禁止 1 人包办整仓）→ 收尾经 `update_project_profile` 合并写项目 **画像 + 导航.md**，记录 `workspace_key` 与指纹；主题软顶 5 / 总数受 `memory_max_topic_files` → **立刻继续原请求**。探索 pending 期间仍禁 worker `form=files`；`文档/项目/` 不在本幕写。

**强制 / 豁免**：点名强制开幕（合并更新）。旧画像无 key → 不因缺 key 硬开。裸聊 / 纯闲聊 / 空工作区不自动开幕、不写假画像/导航。对已有工程「继续开发 / 全面摸底」亦须 ≥2 角并行（提示词纪律；冷启动闸另硬拒单 worker）。探路硬闸**不扫用户原文猜意图**分叉：统一「到限后 delegate，或短答并自报归类（闲聊/单点事实/追问）」；闸后长文一律丢稿再催一次。成篇形状 / 修码选型 / 跑·修·打开验证终向 / 点名对比扇出靠提示词与结构验收，不靠意图分类器（`exec_verify` 用户意图硬闸、`named_entity_fanout` 用户扫硬拒已移除）。成篇审计硬门只认 `playbook=research_report` 与 deliverable 结构字段（如 `min_length≥3000`），不扫 task/角色自由文。

**边界**：不新建 Explore 原语；指纹 = 顶层树 + 关键清单（不以纯天数 / commit 为唯一闸）。产物只落 `AgentCore/`（记忆；厚案卷另见 `文档/` 且不在探索 pending 批）。权威分层 → [记忆 · 探索触发](/docs/03-AI核心/Agent记忆与知识系统.md)。

## 失败与否决（一行）

| 场景 / 方案 | 处理或否决理由 |
|---|---|
| `delegate` 参数非法 | 非终态回 CEO，改参重试 |
| 单 worker 失败 | 按 `on_failure`；宽松扇入默认放行，不必拖垮整 DAG |
| 无需团队 | 不调 `delegate` = 单 Agent 直答 |
| 纯路由器替换 CEO / 前置分类器 / Worker 直连 / 取消 CEO 综述 | 规划壁垒、编排税、不可观测、丧失「一个声音」 |
| 累计 N 次只读软提醒护栏 | A/B 净负已移除；靠提示词边界 + 失控硬兜底 |

## 开场卡 / 检查点

`ask_user` 开工提案卡、`team_preview` 团队预审、`checkpoint_after` 波边界把关 → 全文见 [检查点与开工卡](/docs/03-AI核心/检查点与开工卡.md)，本文不复述。
