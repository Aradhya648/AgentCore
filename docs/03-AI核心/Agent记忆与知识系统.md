---
status: blueprint
code: apps/server/agentcore/memory/
related:
  - docs/03-AI核心/上下文传递可视化.md
  - docs/02-架构/双模式工作区.md
skip_if:
  - 只改 World A/B 提示词架构或 World B 内部工具提示词（读执行引擎 §七）
---

# Agent 记忆与知识系统

> **状态**：MVP 方案已确定（存储基础、分层策略、注入流程）；作用域分层（全局/项目）+ 偏好/画像二分**后端已落地**（§1.4 / §二），项目层双栏画像编辑器 + 主题树浏览·编辑·删除**前端已落地**（§1.6）；维护协议已升级为**两层（情景沉淀 → 低频巩固）**并落地（§1.5）；**「一切皆文档」+ 用户自定义规则 + Document 第一期已落地**（记忆迁 `documents` 表 + 用户规则闭环 + 跨文件预算 + 桌面「你的规则」编辑入口，§五 / §5.7）；`code_search`（BM25 符号检索）已落地（§5.6）；**`AgentCore/` 约定目录**（规则 + 记忆 + `文档/` 案卷）✅ 已落地（§5.0）；embedding 去重 / pgvector 知识库等高级特性待定
>
> → 见代码：`apps/server/agentcore/memory/`、`workspace/indexing/`

---

## 核心问题

在 Multi-Agent First 产品中，每个 Agent 如何持有和管理记忆？多个 Agent 之间如何共享上下文和知识？

---

## 一、MVP 记忆分层 ✅ 已确定

MVP 阶段实现两层记忆，覆盖最核心的用户体验需求。

### 1.1 分层总览

| 层级 | 存储 | 生命周期 | MVP 状态 |
|------|------|----------|----------|
| **工作记忆** | 内存（对话历史 + worker 运行产物） | 会话内 | ✅ 必须 |
| **用户长期记忆** | 文件树 `rule` 文件（`ai_maintained=true`） | 持久化，可演进 | ✅ Day 1 必须 |
| 项目知识库 | pgvector 语义检索 | 跟随项目 | ❌ 延后 |
| 跨 Agent 共享记忆 | — | — | ❌ 延后 |

> **记忆与规则统一**：长期记忆不再是独立的 `user_memory` 表，而是文件树里一个由 AI 维护的 `rule` 文件——与用户写的规则**同载体、同注入管线**，仅靠 `ai_maintained` 布尔位区分「谁可静默改写」。设计依据见 §五；被否决的 `user_memory` 表方案见 §八。

### 1.2 工作记忆（会话内）

当前会话中的即时上下文，即现有运行时数据（对话历史 + worker 产物），无需额外设计层。

### 1.3 自动标题（替代已移除的「会话摘要」）

> **会话摘要记忆层已移除**。理由：跨会话情景对 CEO 分工帮助有限；可复用信号由长期记忆文件（§1.4）承载；相关任务多在同会话续接。仅保留自动标题（侧边栏 UX，非记忆层）。
>
> **与 §1.5 情景沉淀的区别**（勿混淆）：被移除的「会话摘要」是**注入 CEO 上下文**的记忆层（直接影响分工）；两层协议的「情景沉淀」**不注入任何 prompt**，只作语义巩固的内部输入——本条否决依然成立。

唯一保留的是**自动标题**：一句话标题，写入已有的 `conversations.title` 列，仅用于侧边栏展示。它是 UX 特性、不是记忆层——**不进任何 Agent 上下文、不含 `key_decisions`**。

生成走 `title` profile（小 token 上限 + **强制关思考**——曾实证 reasoning 吃光 max_tokens 致正文为空）；空响应重试一次、超时不重试，最终回退为截断的用户首句。→ 见代码：`memory/conversation_title.py`、`llm/profiles.py`。

**生成时机（2026-07 提前，对齐行业实践）**：云 SSE 回合在**用户首条消息落库后**（`turn_saved`）fire-and-forget 与回合并行铸题，**只用首条用户消息**、不等 AI 回复——多 Agent 回合可跑数分钟，等收尾才铸题会让侧栏「新对话」挂到回合结束（首轮挂检查点时更是等到用户决策后）。写库条件化（仅 title 仍空才写，`update_title_if_empty`），关死与用户手动改名的竞态；`title_generated` SSE 可能出现在流中间，sink 已关时放弃 emit、DB 写入不回滚。**本地 sidecar 回写链路维持原时机**（回合结束回写时生成，输入含 AI 回复）——离线辨识由前端乐观占位（截断首条用户消息，替代「新对话」）兜住。**否决**「首轮结束后用完整交换再补铸一刀」：收益小、引入二次覆盖复杂度。

> **对话自动标签已同路退役**（2026-07）：`memory/conversation_tag.py` 与 `conversations.tag` 列整体移除（迁移 `d2e8f1a4c7b9` drop 列），对话归组走项目（Folder）+ 搜索——勿从旧迁移文件反推该功能仍在。

### 1.4 用户长期记忆（AI 维护的记忆文件夹）

用户的长期记忆是文件树里一组 AI 维护的 `role=rule`、`ai_maintained=true` 笔记（与用户手写规则同载体、同注入，区别仅在 AI 可静默改写，详见 §五）。**记忆按位置分两个作用域**（位置即作用域，[§5.3](#53-位置即作用域)——不另立标记位、不给用户手动开关）：用户云端根下是**全局**（注入每次对话），项目文件夹下是**项目级**（仅绑定该文件夹的对话才注入）。`apply_mode` 由位置约定派生（无 manifest）。

> **布局（2026-07-24；文档子树 2026-07-25）**：约定根夹 [`AgentCore/`](#50-agentcore-约定目录)。规则/记忆新写入落 `AgentCore/{规则,记忆}/`；旧裸 `记忆/` / 顶层规则由启动期幂等迁移收口。工作区案卷/副产物落 `AgentCore/文档/`（不注入，见 §5.0）。

```
（全局：云端根 / AgentCore/）
AgentCore/
├── 规则/                    用户硬规则（默认 always）
└── 记忆/
    ├── 偏好.md       always  沟通偏好 + 工作习惯（软、普适、仅全局）
    ├── 画像.md       always  技术栈 + 关于用户的事实
    └── 主题/<slug>.md on_demand  话题 / 经验 / 流程

（项目级：Folder F / AgentCore/；仅 F 内对话注入；无偏好.md）
AgentCore/
├── 规则/
└── 记忆/
    ├── 画像.md       always
    └── 主题/<slug>.md on_demand
```

**为什么是文件夹而非单文件**（驱动是产品 / 架构、**不是** token——1M 窗口装得下，见 §六）：① **作用域**——约定夹可落到项目下，[§5.3 位置即作用域](#53-位置即作用域)天然分「全局 / 项目」两层 ✅；② **记忆类型**——文件夹装得下 episodic / procedural / 主题，不再只有「偏好 / 事实」；③ **统一约定根**——规则与记忆同树（§5.0），不再根上裸挂多套入口。行业坐标：Anthropic Memory Tool（`/memories` 文件夹 + 反向量）、Letta/MemGPT 佐证「记忆 = 文件夹 + agentic 自取」（与 §5.6 反向量决策一致）。

**always 核心 = `偏好.md` + `画像.md`（按「怎么对我 vs 关于我」二分）** ✅：常注入核心是两个文件——`偏好.md` 收 `沟通偏好`/`工作习惯`（软、普适、**仅全局**），`画像.md` 收 `技术栈与工具`/`关于用户的事实`（较硬、可全局可项目）。两者都沿用**固定小节锚点**纪律（内容始终归位固定小节，防自由文本漂移；维护协议已升级为「巩固期整文件重写」，见 §1.5），写入路由带「**作用域 + 文件**」两维。**为何拆、为何此时拆**：阶段一曾否决二分（无第二作用域时纯属预支复杂度）；其价值由作用域解锁——有了项目层才出现「偏好天生全局、不该复制进每个项目；只有事实/知识按项目变」这条真实分界，故 A（作用域）、B（偏好/画像）同期落地。分文件 = 分 CAS、分变更原因，整理边界清爽。

**作用域规则与关键决策（现状）**：

- **叠加注入，不替换**：绑定文件夹的对话注入「全局 + 该项目」两层；与全局规则共享同一 `MAX_INSTRUCTION_*` 口径，紧张时**全局优先存活**（§5.3）。裸聊（无文件夹）只有全局；委派 worker 继承两层。
- **项目层只放事实/知识、不放偏好**：偏好（怎么跟我沟通）天生普适，故项目 `记忆/` 无 `偏好.md`——避免把全局偏好复制进每个项目（这是 B 由 A 解锁的核心断言）。
- **冲突不做硬覆盖结构**：同一事实全局 vs 项目相左（如全局「我用 Python」/ 本项目「这仓用 Rust」），靠措辞 + 就近相关性化解，注入时项目段带「仅本项目适用」标签；用户手写硬规则恒胜（§二）。
- **作用域靠位置、不靠开关**：跟着对话的 `folder_id` 走，**不**给用户手动「这条记哪」开关（对齐 [`双模式工作区.md`](/docs/02-架构/双模式工作区.md)「模式跟着文件走」）。暂不做「按项目关记忆」的细粒度开关，沿用全局 `memory_enabled`（无第二需求不抽象）。
- **过渡 vs 终点 ✅ 已收口（2026-07）**：记忆已自 `FileMemoryStore` 迁入 `documents` 表——`DocumentMemoryStore` 实现同一 `MemoryStore` 协议换底，注入 / 巩固 / 编辑器 REST / CAS 上层零改动。项目作用域现由 `documents.folder_id` 列桥接承载（工作区 Folder 尚未并入文档树，「`parent_id IS NULL` = 全局」的同形终态待 Folder 并树后折叠，过渡决策见 §5.7）。

**on_demand 主题（`主题/<slug>.md`）**：`<记忆主题目录>` 列**主题名＋一行摘要**（摘要＝主题文件首行，由 `topic_summary_line` 在 render 时带出并截断以护前缀缓存；空/仅 chrome 的笔记只列名），CEO 按需用 `consult_memory(name)` 把全文拉回（注入分层见 §二）——文件夹解锁的新记忆类型靠这条按需通道承载，正文不挤常驻前缀。

**注入语气**：内容用软措辞（「倾向于」而非「必须」）。权威性由措辞携带——AI 推测的偏好与用户硬规则冲突时，以用户规则为准（见 §二）。

**迁移（一次性、幂等）**：两代迁移同纪律（best-effort、失败保留源文件、不丢数据）——旧单文件 `<user_id>.md` → `记忆/画像.md`；file store → `documents` 表（skip-if-exists、不覆盖迁移后编辑）。→ 见代码：`memory/document_store.py`（`DocumentMemoryStore`，CAS = 内容 sha256 不变）、`memory/migrate_documents.py`。

### 1.5 记忆维护协议（两层：情景沉淀 → 低频巩固）✅ 已落地

> **2026-07 定案升级**：原「每场会话收尾由 flash 一步产 ops 直写画像」协议被否决，升级为两层。**为什么**：一步式要求模型在**单场窗口**上判断「持久事实还是临时热点」——持久性只有跨会话的时间维度能证明，单窗口原理上答不了。测试期日志实证（近 7 天）：113 条写入约 35% 为会话琐事或跨场重复（「正在测试 X」类任务态进画像；同类事实反复 add，LV 案相关占 33/113）；173 次抽取仅 39 次真变更（约 62% 空转）；增量 ops 下「add 永远比 update 容易」，字面去重挡不住同义改写。

| 层 | 触发 | 行为 | 前端 |
|---|---|---|---|
| **情景沉淀**（episodic） | 每场会话收尾（静默 debounce / 轮数上限，参数见 `config/persistence.py`） | 写一条 ≤200 字会话摘要（做了什么、结论、偏好信号），按用户/作用域**追加**；不去重、**不注入 prompt**，仅作巩固输入 | 轻提示 |
| **语义巩固**（semantic） | 未消化情景 ≥3 场 **或** 距上次成功巩固 ≥24h（均可配置） | 输入 = 现有画像全文 + 未消化情景列表；`偏好.md`/`画像.md` **整文件重写式**输出，`主题/*.md` 保留 ops；CAS + `memory_updates` 审计防丢 | diff 卡片 |

- **琐事与重复的消解是机制性的，不靠门槛**：只出现在单条情景里的任务态在聚合视角天然不构成模式；跨场重复信号在重写输出里天然只剩一份。
- **异常回合沉淀闸门 ✅**：`consolidate_conversation` 统一入口跳过 cancelled / interrupted / error / 无实质收口的回合（不把假暂停、硬杀、用户停止的半成品写进情景）；跳过仍**推进 watermark**（防 sweeper 空转），打 `memory.consolidation_skipped_abnormal_turn`。
- **偏好须明示 ✅**：情景沉淀与语义巩固 prompt 均约束——偏好只能来自用户**明示或纠正**，禁止从任务题材推断（如「用户在测法律案」≠「偏好法律分析」）；`偏好.md` 升格须摘要带明示证据。
- **重写防丢双闸**：空重写不可清空文件；重写若静默丢弃过多既有条目（保留率 < 50%）整体拒绝落盘，episodes 留待下轮重试；真变更以 bullet 级 diff 记 `memory_updates` 审计（即 diff 卡片数据源）。
- **巩固失败不推进**：LLM 解析失败/超时 → episodes **不标记已消化**，下轮触发自动重试；成功（含无变更）才标记，防止同批情景被反复合并。
- **显式记住例外**：用户明确要求记住的内容经 CEO `remember` 工具**直写语义层、立即生效**，不等巩固——用户显式意图无需「时间证明持久性」。工具描述已约束「仅用户清楚说记住时用；推测偏好交给离线巩固」；`remember` 受 `memory_enabled` 总开关闸，`consult_memory` 另需本回合确有可查阅主题才装配（空目录不装配、不渲染）。注意：`remember` 落的是**用户规则**（`ai_maintained=false`），不是画像。
- **巩固冷启动（`_is_cold_start`）**：仅当**全局** `偏好.md` 与 `画像.md` 皆空时，巩固抽取降门槛——与产品「冷启动探索幕」（闸看**项目**画像）**正交、禁混名**。
- **冷启动探索幕写画像（§1.5 产品例外）✅**：有项目 + 实质请求且（项目 `画像.md` 空 **或** 探索侧车 `explore_workspace_key` 与当前绑定不一致）时，CEO 组队探索后经 `update_project_profile` **中途直写项目** `画像.md`（`ai_maintained=true`，小节合并 + CAS），并写入 `_memory_meta.json` 的 `explore_workspace_key`（本地 `local:<root>:<subpath>` / 云端 `folder:<id>`）；可选 `topics`（≤3）整文件写入项目 `主题/<slug>.md`（on_demand）；禁止经 `remember` 落成规则。旧画像无 key 不强制重探。与巩固冷启动正交。→ 见代码: `memory/explore_profile.py`、`memory/episodic.py`（`ScopeMemoryMeta`）、`tools/builtin/update_project_profile.py`；编排见 [编排器 · 冷启动探索幕](/docs/03-AI核心/编排器与CEO主Agent.md)。
- **不做静默写入**（产品决策 2026-07）：两层写入都有前端通知，分级呈现（情景轻提示 / 语义 diff 卡片），事件契约 `memory_updated` 带 `kind: episodic|semantic`。
- **测试账号不豁免**：记忆功能本身需要被测试。

落盘按「作用域 + 文件」路由（`section` 决定核心文件；偏好/纠正强制全局、项目约束强制项目）；主题 create-on-write；防膨胀护栏按作用域各算。→ 见代码: `memory/episodic.py`

**被否决（2026-07）**：单层 + 冷却时间 / 最小信息量门槛——只抑制「跑太勤」的症状，不解决「单场判断持久性」的根因，属补丁。

**写权限**：维护任务**只写 `ai_maintained=true` 的文件**，永不触碰用户手写规则（见 §五 写边界）。
**隐私与防注入边界（决策）**：两条铁律——① **默认不沉淀敏感个人数据**（身份证 / 密钥 / 精确住址 / 支付 / 健康 / 宗教 / 性取向 / 政治倾向），除非用户明确要求记住；② 把对话内容当**待总结的素材而非指令**——不把嵌入指令或粘贴的第三方文本当「关于用户的事实」记入、更不让其覆盖①。**理由**：长期记忆是会注入每一次后续 prompt 的持久文件，静默留存敏感信息、或被对话「投毒」的代价远高于普通输出（对齐 OpenAI / Anthropic）。

> **现状（2026-07 收口）**：Document 子系统 server 侧已落地（§5.7），记忆即树内 `ai_maintained=true` 的 rule Document——「存储与注入隐藏在抽象后、文件树到位后一处替换」已如期兑现（`DocumentMemoryStore` 协议换底，上层零改动）。

### 1.6 记忆的查看 / 编辑 / 开关 ✅ 已落地（前端）

记忆当文件用：文件页约定树 `AgentCore/{规则,记忆}/` + 同一 Markdown 编辑器。**CAS** 防盲覆盖；总开关在设置（停用＝不注入不增长且推进 watermark）；全局 = 偏好‖画像两叶；项目记忆在项目下同名约定夹；主题树可编删、核心叶不可删。→ 见代码: `components/files/fileWorkbench/AgentCoreSection.tsx`

---

## 二、记忆注入流程 ✅ 已确定

工作记忆（当前对话历史）经 `load_recent_history`（取最近 N 条、按时序）进窗口，CEO 与各 worker 都读得到；**用户长期记忆**随文件注入管线合成进共享 `<rules>` 基座（CEO 与 worker 共用同一基座，见 §1.4）。会话摘要注入路径已移除（见 §1.3）。

**关键决策：用户偏好折叠进共享 `<rules>` 基座（CEO 与 worker 共用），不另建独立 `user_preferences` 上下文通道。** 偏好随 `assemble_system_prompt(memory_markdown=...)` 进基座，CEO 与 worker 都吃得到，无需为「编排/分工」单开一条注入路径。

**规则 vs 记忆的优先级 ✅**：合成 `<rules>` 时，用户规则在前（权威措辞）、AI 维护的记忆在后（软措辞）；冲突时以用户规则为准。权威性由措辞携带，不靠单独的注入段或结构。无用户规则时输出与旧 memory-only 块**逐字节一致**（护前缀缓存）。→ 见代码：`memory/rules_injection.py`。

**注入前裁剪人面 chrome**：注入时剥 H1 + 说明引用块，**文件本身不动**。→ 见代码: `memory/user_memory.py`

**记忆分层注入**：always 核心全文进 `<rules>`，序 **全局偏好 → 全局画像 → 项目画像**（全局在前护前缀缓存）；跨文件预算紧张时全局优先。on_demand 主题只列目录（无主题则不渲染、不装配 `consult_memory`），有主题时按需拉全文（项目优先、全局兜底；错名软 miss、非工具失败）；与 `memory_enabled` 同闸。→ 见代码: `memory/rules_injection.py`

**挂起→恢复接线 ✅**：`folder_id` 与 `memory_enabled` 随挂起帧持久化；旧帧兜底全局/开。→ 见代码: `runtime/suspension.py`

**同回合 consult 复用 ✅**：同 key 命中缓存不重复打 store。→ 见代码: `runtime/memory_consult_cache.py`

---

## 三、记忆生命周期

**触发点**：会话开始加载 `ai_maintained` 记忆 → 进行中累积工作记忆（云回合首条用户消息落库时并行铸标题，§1.3）→ 会话收尾沉淀一条情景摘要 → 情景积累到阈值（≥3 场或 ≥24h）触发语义巩固重写画像（两层协议见 §1.5）。→ 见代码：`memory/`、`runtime/pipeline/`。

---

## 四、运行时上下文管理 ⏳ 远期上下文工程

> **MVP 范围**：DeepSeek V4 的 1M 窗口足够容纳 MVP 全部记忆（见 §六），本节 TWM / recall / 委派预算等**延后到窗口不足时实现**。MVP 只做「工作记忆 + 记忆文件注入」。

上下文分 8 类（行为 / 参考 / 历史 / TWM / recall / 委派 / 产物 / 运行时身份）跨 5 种边界传递（轮内装配、跨轮快照、跨 turn、跨 Agent 委派、跨进程）。核心远期机制：

- **TWM**：Agent 经 `update_task_state` 维护 goal/plan/findings 结构化状态，作钉住块不被裁剪。
- **Agentic Recall**：窗口裁剪内容归档为可寻址 artifact，Agent 经 `recall(id)` 精确取回。
- **布局原则**：易变块（TWM、归档索引）后置，保护 history 前缀缓存命中。
- **跨 turn 历史**：只回放 user/assistant 文本——见 [`执行引擎架构设计.md` §三](/docs/03-AI核心/执行引擎架构设计.md) 历史重建原则。
- **委派预算（参考）**：基底摘要 ~2500 字符、链合成上限 ~6000 字符；**深度 `depth ≤ 2`**（`MAX_DELEGATION_DEPTH`）；单次 `delegate` 最多 20 个子任务（`MAX_DELEGATION_TASKS`，整批拒绝 + 分批指引）、树内并发上限默认 12（配置项 `engine_max_parallel_delegations`，回落常量 `MAX_PARALLEL_DELEGATIONS`，超额排队）。

详述与预算表见 远期规划（详细提案不在公开仓 / 维护者本地）。

---

## 五、工作区上下文模型 ✅ 已确定

> 统一到文件系统：用文件替代独立 Memory 模块，参考 Cursor 的工作区模型——rules 是文件、docs 是文件、AI 上下文就是文件。
>
> **「一切皆文档」已落地为架构现状。** 规则 / 记忆 / 知识文档不是三个功能，是同一实体（md 文档）在三个正交元数据维度上的取值：**谁写**（`ai_maintained`，§5.2）×**作用域**（位置即作用域，§5.3）×**注入策略**（`apply_mode`，§5.4）。载体 = Document 子系统（单表 `kind`×`role`，约定见 [核心接口定义 §6.2](/docs/02-架构/核心接口定义.md)）；记忆自 `FileMemoryStore` 迁入；用户规则 = `role=rule, ai_maintained=false`——第一期边界与落地现状见 §5.7。
>
> **被否决**：① 照搬 Cursor rules 形态（用户手写规则文件心智 + globs 条件注入为主入口）——大众用户不手写规则文件，文件 globs 在对话产品无附着物；② 轻量先行（先在 `FileMemoryStore` 过渡态上接 `ai_maintained` 两档措辞、Document 子系统另行排期）——被「直接立 Document 子系统」替代，避免记忆二次迁移。

### 5.0 `AgentCore/` 约定目录 ✅

> **问题**：元模型已统一（谁写 × 作用域 × 注入），但物理布局与 IA 曾分裂——根上裸挂 `记忆/`、规则散落 / 双 rail。目标演进为**一个可见约定根夹**管齐 AI 相关文档：进 `<rules>` 的规则与记忆，以及**不注入**的工作区案卷/副产物。

**夹名与可见性**：用户可见 **`AgentCore/`**（产品名；不设点前缀隐藏）。与本地技术旁路 **`.agentcore/index/`**（`code_search` 索引，gitignore）**正交、不混用**。**勿与本地盘默认路径 `~/Documents/AgentCore/`（工作区容器）混淆**——同名异载体。

**双层语义（硬边界）**：

| 子树 | 载体 | 注入 | 状态 |
|---|---|---|---|
| `规则/` · `记忆/` | documents | always / on_demand → `<rules>` | ✅ |
| `文档/` | **工作区盘** | **永不**进 always `<rules>`；按需 `file_read` | ✅ |

**作用域**：云端根下 `AgentCore/` = 全局；项目 Folder 下同名夹 = 仅该项目。规则/记忆叠加注入、全局优先存活（§5.3）不变。`文档/` 随工作区绑定走（项目共享 / 裸聊 scratch）。

**约定树**：

```
AgentCore/
├── 规则/                 role=rule, ai_maintained=false
│   └── *.md              默认 always；超长规则可选 on_demand（预留）
├── 记忆/                 role=rule, ai_maintained=true
│   ├── 偏好.md           always（仅全局）
│   ├── 画像.md           always
│   └── 主题/<slug>.md    on_demand（`consult_memory`，现状保留）
└── 文档/                 工作区相对路径，不注入
    ├── research/         调研案卷（MLR）
    ├── debate/           辩论收场产物
    └── reviews/          审查 / 其它副产物
```

案卷路径权威：后端 `workspace/stage_dirs.py`；桌面/手机 `lib/stageDirs.ts`。机制 → [双模式工作区 · 阶段产物](/docs/02-架构/双模式工作区.md)。

**按需注入（已确认策略）**：

| 内容 | 模式 | 理由 |
|---|---|---|
| 用户硬规则 | 默认 **always** | 行为约束模型不会主动去查；缺了≈不存在 |
| 偏好 / 画像 | **always** | 同上；不改为 on_demand |
| 记忆主题 | **on_demand** | 现状 `consult_memory` |
| 超长用户规则 | **可选** `on_demand` | 能力预留；默认仍 always |
| `文档/**` | **不注入** | 案卷/副产物；概览 + `file_read`，禁止当规则喂模型 |

**注入收集**：always 规则/记忆核心由 `list_injectable_rules` 按 **role + `folder_id` + `apply_mode=always`** 收（**不**按树直子级 walk）。约定目录已存在时加 parent 闸：用户规则须 `parent_id == AgentCore/规则/`；记忆 always 核心须在 `AgentCore/记忆/`（过渡期仍允许未迁完的裸 `记忆/` 父节点）。无约定夹时保持旧口径（防半迁移读空）。**`文档/` 不进 documents 注入闸**。

**迁移（规则/记忆）**：启动期幂等把裸 `记忆/`、既有顶层用户规则迁入约定树；失败保留源、不丢数据（对齐 §1.4）。双根折入后若裸 `记忆/` 无 live 子节点 → **软删**（`deleted_at`）；仍有子节点（name clash 留下）则保留并打日志。`ensure_memory_root` / `upsert_user_rules_doc` / 前端 `listUserRules`·`createRuleDocument`（API 对 `role=rule` + `parent_id=null` 自动挂到 `AgentCore/规则/`）已同步。IA：文件页单一 `AgentCore/` 段，无双 pinned rail。→ 见代码：`memory/migrate_agentcore.py`、`db/repositories/documents.py`、`fileWorkbench/AgentCoreSection.tsx`

**文档子树（2026-07-25）**：开发期**直切** `AgentCore/文档/{research,debate,reviews}/`；**无**根级旧路径兼容层。写盘教法 / skill / `stageDirs` / 辩论 persist 已对齐。

**被否决（2026-07-24）**：独立 `AgentCore/知识/` 子树 + **知识目录注入**——并无独立「可注入知识库」产品功能；documents 与工作区盘双载体下「正文走 file_read」接不上注入。远期 pgvector「项目知识库」（§七）仍另案。

**被替代（2026-07-25）**：案卷层与 `AgentCore/`「正交、不合并」——改为案卷收进 `AgentCore/文档/`，仍不注入；产品心智 = **一个根管齐 AI 相关文档**。

**明确不做 / 现状（本蓝图）**：把偏好/画像改 on_demand；用隐藏点目录替代可见 `AgentCore/`；与 `.agentcore/index` 合并；为 `文档/` 新建 `consult_knowledge` / always 注入；根级案卷双读兼容。**主题不改为真实嵌套 folder**：继续 `name=主题/<slug>.md` + `parent=记忆/`，前端合成「主题」节点——属有意设计（保住 MemoryStore 路径语义），非未完成残留。

### 5.1 文件夹 = 对话的上下文边界

不引入新实体。**任何文件夹天然就是对话的上下文边界**，对话关联到哪个文件夹，那个文件夹的文档就是该对话的上下文。类比 Cursor：打开项目目录 = 进入该项目的上下文。

- 对话创建时可选文件夹，也可不选
- 已绑定的对话不可解绑、不可迁移（`folder_id` 一旦设置即为终态）
- 无文件夹的对话仍受账号级全局规则约束

### 5.2 文件角色模型（记忆与规则统一）

记忆与规则**同载体、同注入**：合并为单一 `rule` 角色，仅靠 `ai_maintained` 布尔位区分「谁可静默改写」。

| role | ai_maintained | 含义 | 注入行为 |
|---|---|---|---|
| `rule` | `false` | 用户规则（用户拥有，AI 可起草但不静默改） | 按 `apply_mode` 进入 `<rules>` |
| `rule` | `true` | AI 维护的长期记忆 | 进入 `<rules>`（默认 `always`，软措辞） |
| `general` | — | 普通文件/文档 | 列入 `<workspace_file_index>` 概览，Agent 按需 `file_read`/`grep` 取正文（见 §5.6） |

用户视角：`rule + ai_maintained=false` 显示为"规则"，`rule + ai_maintained=true` 显示为"记忆"，`general` 是普通文档。

**为什么不合并成一种、也不拆成两个角色**：注入进 prompt 后一切都是文本，「权威 vs 推测」无法靠结构硬性区分，由内容措辞携带即可——所以无需独立的 `preference` 角色。但「后台维护任务可静默改写哪些文件」是**代码层安全分支**：类比 repo 里「手写文件 vs 生成文件」都是文件、却必须标记以免工具乱改。`ai_maintained` 就是这个标记，删不得。`instruction` / `preference` 旧二分见 §八 否决记录。

### 5.3 位置即作用域

全局规则不靠标记位，而靠**位置**：放在云端根（`parent_id IS NULL`）的 `rule` 文档注入所有对话。子文件夹的 `rule` 只对该文件夹上下文内的对话生效。

- 全局规则与文件夹规则共享同一注入预算口径（`MAX_INSTRUCTION_*`），不各自一份 ✅（随 Document 第一期落地，见 §二 / §5.7）
- 累积合并时**全局优先**（始终生效基线，预算紧张时优先存活）
- 委派子 Agent 继承用户全局规则，避免父子行为约束分裂

### 5.4 注入模式

`rule` 文档支持三种 `apply_mode`（用户规则与 AI 记忆通用）：

| 模式 | 行为 | 字符预算 |
|---|---|---|
| `always`（默认） | 全文注入 `<rules>` | 计入 `MAX_INSTRUCTION_CHARS` |
| `conditional` | 按场景条件注入。Cursor 的触发器是文件 globs，对话产品无对应物；「条件性」的主要需求已由**位置作用域**（§5.3，正交维度）承担，场景级触发器（按工具/任务类型）⏳ 待真实需求，现阶段不做 | 计入 |
| `on_demand` | `<rules>` 仅列名，Agent 经 consult 工具按需拉全文 | 不计入 |

> **为什么规则/偏好占 always、知识占 on_demand**（2026-07 定案时明确）：规则约束的是 AI **意识不到的行为盲区**——知识缺了模型会主动去查，规则缺了模型不会去查「用户有没有规定过这个」，不常驻就等于不存在。on_demand 的最小形态也是「摘要常驻」（目录一行），真正零常驻的只有 conditional（靠外部触发器）。

> **on_demand 现状**：今日唯一接线的 on_demand 消费者是**记忆主题**（`主题/*.md`，经 `consult_memory`，见 §1.4 / §二）。面向**用户手写规则**的通用 `consult_rule` 尚未实现——按「第 3 次真重复才抽象」留到出现第二类 on_demand 规则消费者或扳机 A 触发时再建（见 [上下文工程](/docs/03-AI核心/上下文工程.md)）。

### 5.5 上下文装配顺序

> 本节为「上下文装配顺序」**单一权威**（[执行引擎 §七 提示词架构](/docs/03-AI核心/执行引擎架构设计.md) 指此取顺序细节）。

每个常驻上下文源都是一个 `PromptContributor` 小插件（`key` + 正文 `text` + 渲染序 `order` + 预留 `budget`），由 `runtime/context/assembler.py`（`ContextAssembler`）统一收集，按 `order` **稳定排序**后以 `\n` 拼接；正文为空的源该回合自动丢弃（不留空行）。渲染序由 `SectionOrder` 单一枚举声明（**非**各调用点 `.add()` 的书写次序），间隔 100 留插槽：

```
BASE 100 → RUNTIME_CONTEXT 200 → MEMORY 300 → CEO_CORE 400
→ SKILL_DIRECTORY 500 → MEMORY_TOPICS 550 → CITATION 600 → CEO_VISUALIZATION 700 → WORKSPACE_OVERVIEW 800 → ATTACHMENT 900
```

这是**一套**排序坐标系；并非每条路径都用满全部档位（worker 走 `BASE`/`RUNTIME_CONTEXT`/`MEMORY`/`ATTACHMENT`，CEO 聊天走 `BASE`/`CEO_CORE`/`SKILL_DIRECTORY`/`MEMORY_TOPICS`/`CITATION`，再叠 `WORKSPACE_OVERVIEW`/`ATTACHMENT`），但两路径对相对顺序的认知永远一致。`MEMORY_TOPICS`（记忆主题目录，CEO-only）紧挨 `SKILL_DIRECTORY`：二者同形——都是「列个目录、按名拉全文」的按需块（见 §二）。

> **决策：常驻源统一为 contributor 插件、顺序声明化。** 理由：① 新增常驻源只需声明一个 `order` 即落位，无需在某个拼接点插队、改动多处调用；② 渲染序与贡献次序解耦——各调用点本就按升序贡献，稳定排序复现原内联顺序、原 `\n` 拼接，**与统一前逐字节一致**（稳定前缀不变，DeepSeek 前缀缓存不破）；③ 稳定前缀（base + hints）在前、概览 / 附件置尾，护前缀缓存（概览 / 附件都空时与原 CEO 提示词逐字节一致）；④ `budget` 字段为「扳机 B」（预算 / 裁剪 / 降级）预留**唯一读取点**——今天不强制裁剪，按需才长（触发条件见 [上下文工程](/docs/03-AI核心/上下文工程.md) 扳机 B）。→ 见代码：`runtime/context/`（`contributor.py` 定义形状 + `assembler.py` 收集排序）。

**Workspace Context（CEO）= 实时工作区概览 + 工作区画像** ✅：每回合 `build_workspace_overview(backend)` 先 best-effort 检测工作区画像（`detect_workspace_profile`：语言/框架/包管理器/monorepo 工具/VCS 分支/常用命令/`AGENTS.md` 摘录；**只读清单文件、不执行命令**；画像 ≤600 字符；失败不阻塞），再拉「最近更新在前」的文件清单（文件数 + 字符预算双重封顶），一并注入 `<workspace_file_index>`（`WORKSPACE_OVERVIEW` 档）。**工作区感知是上下文注入增强、不是新工具**；延续 agentic 检索路线，不上向量 RAG。worker 不走此块——它们已有更丰富的逐运行 manifest。→ 见代码：`runtime/context/workspace_overview.py`、`runtime/context/workspace_profile.py`。

⏳ **Marketplace Rules**：市场 Rules 绑定待能力域落地后接入装配链。

### 5.6 搜索范围设计

限制发生在**内容量层面**（多少 token 进 prompt），而非结构层面（多少层文件夹）：

| 机制 | 范围 | 限制手段 |
|---|---|---|
| `rule` 注入（规则 + 记忆） | **现状 / §5.0 后**：按 scope 的 `role=rule` + `apply_mode=always`（`list_injectable_rules`）；**不**按树直子级 walk；约定夹存在时再闸 `parent_id` 到 `AgentCore/{规则,记忆}/`（裸 `记忆/` 过渡期仍收） | `MAX_INSTRUCTION_DOCS` / `MAX_INSTRUCTION_CHARS` |
| 工作区概览（`<workspace_file_index>`） | 工作区画像 + 关联文件夹文件清单（**整棵子树**，最近更新在前） | 画像 ≤600 字符；文件数 + 字符预算双重封顶；只列路径与元数据、正文不进概览 |
| Agentic 检索（`file_read` / `grep` / `code_search` / `file_list` / `git`） | **整棵子树**（`file_list` 递归树有 `max_depth`/条目上限） | Agent 自取正文；`file_read` 支持 `offset`/`limit` 行号范围；单次工具输出截断 |

`rule` 不按整树递归扫是因为按 scope + role 生效；工作区不限深度是因为用户心智是"文件夹里的东西 AI 都能看到"——**不把向量 chunk 自动灌进 prompt**：概览给方位、Agent 用文件工具 / `code_search` 自取（agentic 检索为主路）。

> **决策：取消向量 RAG（pgvector / embedding）作为 prompt 自动注入层，改用「实时概览 + agentic 检索」。** 理由：① 向量索引一改文件就失效，需 embedder + pgvector + 重建管线，与"文件随时变"的工作区天然不合；② 关键词 `grep` + Agent 自取，在工作区规模（数十～数百文件）下召回足够、永远新鲜；③ 项目知识库级 pgvector **仍为远期**（§七），触发条件见 [上下文工程](/docs/03-AI核心/上下文工程.md) 扳机 A。

✅ **`code_search` 工具已落地**（BM25 符号级检索，与上条决策兼容）：

| 约束 | 口径 |
|---|---|
| 索引旁路 | 索引是**工具后端**，**不是** prompt 自动 RAG 层——命中后仍由 Agent 决定是否 `file_read` 精读 |
| 与 `grep` 并存 | `grep` = 精确正则逐行（内嵌 ripgrep / Rust regex）；`code_search` = 意图/概念入口（tree-sitter 分块 + BM25，符号列加权；空命中附建议 grep 关键词，不静默二次调用） |
| 刻意不做 prompt RAG | **否决**纯向量 chunk 注入 system prompt；嵌入 / 调用图为可选后手，不上自动装配链 |
| 存储 | 工作区旁 `.agentcore/index/`（`code_search.db`，gitignore）。云端与 sidecar（`ServerWorkspace`）直连盘；云遥控桌面的 `LocalWorkspace` 经通道读文件、索引缓存在服务端 `data_dir/code_index/`（✅ 2026-07-23）。 |

→ 见代码：`tools/builtin/code_search.py`、`workspace/indexing/`；工具契约见 [工具与能力系统](/docs/03-AI核心/工具与能力系统.md)。前端 CommandPalette Tier 3 语义检索为另一层（见 远期规划 §三（详细提案不在公开仓 / 维护者本地））。

### 5.7 Document 子系统第一期边界（✅ server + 前端规则入口均已落地）

§五头部定案的实施切分。**第一期 = 载体 + 迁移 + 用户规则最小闭环**：

| 块 | 内容 |
|---|---|
| 载体 | `documents` 单表（`kind`×`role`×`ai_maintained`×`apply_mode` + `parent_id` 树，约定见 [核心接口定义 §6.2](/docs/02-架构/核心接口定义.md)）+ repository + 树 CRUD API |
| 记忆迁移 | `FileMemoryStore`（全局 + `_folders/<folder_id>/` 项目层）整体迁入树内 `ai_maintained=true` rule 文件；注入 / 两层巩固 / 编辑器 / CAS 全链路改走 Document——§1.4「文件树到位后一处替换收口」在此兑现，迁移一次性、幂等、失败不丢数据（同 §1.4 先例） |
| 用户规则 | `role=rule, ai_maintained=false`。入口两个：① 对话内用户明确指令 → `remember` 工具按「用户拥有」落规则文件（与 AI 推测偏好走巩固的分流既有，见 §1.5 显式记住例外）；② 文件页直接编辑，与记忆同一编辑器形态、「你定的规则」与「AI 记住的」分区展示。注入沿 §二既有两档：用户规则前置 +「必须」，AI 记忆后置 +「倾向于」 |
| 跨文件预算 | `MAX_INSTRUCTION_DOCS` / `MAX_INSTRUCTION_CHARS` + 全局优先存活（✅ 兑现 §5.3），替代记忆的逐文件 cap 单轨 |

**server 侧落地现状**：四块全部就位。**过渡态决策：项目作用域由 `documents.folder_id` 列桥接**——Folder 并树后折叠为「`parent_id` 位置即作用域」。→ 见代码: `memory/document_store.py`

**前端第二刀 ✅**：「你的规则」薄树与记忆区形态对称（rail 根集中）。→ 见代码: `components/files/fileWorkbench/RuleSection.tsx`。决策理由见 §1.6。

**第一期明确不做**：场景级 `conditional`（§5.4，无触发器附着物）；规则 `on_demand` + `consult_rule`（规则量未增长，always 档够用——届时它是第 3 个真 consult 源、触发扳机 A 抽 `Consultable`，见 [上下文工程 §五/§七](/docs/03-AI核心/上下文工程.md)）；agent / 团队级绑定（无 agent 实体可挂，随能力域蓝图 `agent_entity_bindings`）；Marketplace Rules（§5.5 ⏳ 不变）；对话级规则（`conversations.instructions` 已试过并撤回，不复活）。

---

## 六、与 LLM 上下文窗口的关系

DeepSeek V4 有 1M token 上下文窗口，MVP 合计约 13K–73K，远小于窗口——**仅实现基础上下文管理（工作记忆 + 用户长期记忆文件注入）**，复杂压缩/裁剪留待窗口不足时实现。

---

## 七、MVP 范围 vs 未来

| 能力 | MVP | 未来 |
|------|-----|------|
| 工作记忆（当前会话） | ✅ | — |
| 用户长期记忆（`ai_maintained` rule 文件） | ✅ Day 1（轻结构化 markdown）；✅ 项目级作用域 + 偏好/画像二分（后端，见 §1.4 / §二）；✅ 项目层双栏画像编辑器 + 主题树浏览·编辑·删除（前端，见 §1.6）；✅ 两层维护协议（情景沉淀 → 低频巩固重写，见 §1.5） | embedding 去重 |
| 自动标题（侧边栏 UX） | ✅ Day 1 | — |
| 记忆可见/编辑 | ✅ 文件页 `AgentCore/记忆/`（全局偏好/画像 + 项目画像/主题；同编辑器 / CAS，见 §1.6 / §5.0） | — |
| 用户规则可见/编辑 | ✅ 文件页 `AgentCore/规则/`（全局 + 项目；同编辑器 / CAS，见 §5.0 / §5.7） | Marketplace Rules / `consult_rule` |
| `AgentCore/` 约定目录（规则+记忆+文档） | ✅ 规则/记忆注入树 + `文档/` 案卷写盘直切（§5.0；主题 slash-in-name 为有意设计；无根级案卷兼容） | — |
| 记忆总开关（启用/停用） | ✅ 设置→「AI 记忆」，每用户 `memory_enabled`（停用＝不注入＋不增长，见 §1.6） | — |
| 项目知识库 | ❌ | pgvector 语义检索 |
| 跨 Agent 共享记忆 | ❌ | 共享知识图 |
| 运行时上下文工程（§四 TWM/recall/委派预算） | ❌ 延后 | 窗口不足时 |
| 遗忘机制 / 导入导出 | ❌ | 基于访问频率衰减、用户迁移 |

> **被否决方案**：独立 `user_memory` 表 + 独立 `preference` 角色——与文件系统职责重叠、记忆对用户黑盒。改为 `ai_maintained` 的 `rule` 文件统一承载。

---

## 八、待定

| 议题 | 说明 |
|------|------|
| — | （原「维护触发频率」议题已于 2026-07 定案：两层协议，情景每场沉淀、语义低频巩固，见 §1.5） |
