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

> **边界**：记忆分层 / 注入 / 约定目录 = **本文**；通道可视化 → [上下文传递可视化](/docs/03-AI核心/上下文传递可视化.md)；是否统一 ContextProvider → [上下文工程](/docs/03-AI核心/上下文工程.md)；云/本地 Backend → [双模式工作区](/docs/02-架构/双模式工作区.md)。
>
> → 见代码：`apps/server/agentcore/memory/`、`workspace/indexing/`

---

## 一、分层

| 层级 | 载体 | 生命周期 | 状态 |
|------|------|----------|------|
| **工作记忆** | 对话历史 + worker 产物 | 会话内 | ✅ |
| **用户长期记忆** | 文件树 `rule` + `ai_maintained=true` | 持久、可演进 | ✅ |
| 项目知识库 / 跨 Agent 共享 | — | — | ❌ 延后 |

记忆与规则**同载体、同注入**，仅靠 `ai_maintained` 区分谁可静默改写。作用域靠**位置**（全局 = 云端根；项目 = Folder 下同名夹），不另立开关。

```
AgentCore/
├── 规则/                 用户硬规则（ai_maintained=false，默认 always）
├── 记忆/                 AI 维护（ai_maintained=true）
│   ├── 偏好.md           always · 仅全局 · 沟通/习惯
│   ├── 画像.md           always · 技术栈/事实（可全局可项目）
│   ├── 导航.md           always · 仅项目 · 短入口（一句话定位 + 任务路由）✅
│   └── 主题/<slug>.md    on_demand · consult_memory（单次软顶 5；总数≤memory_max_topic_files）✅
└── 文档/                 工作区盘 · 永不进 <rules> · 按需 file_read
    └── 项目/…            厚案卷（探索 pending 不写；闸清后/普通回合）✅
```

- 叠加注入：绑定文件夹的对话 = 全局 + 该项目；预算紧张时**全局优先**；项目层无 `偏好.md`。
- **双层项目知识**：短入口 = `导航.md`（always，只指路、不塞长文）；厚内容 = `主题/` + `文档/项目/`（按需查）。不写用户仓库根 `AGENTS.md` / `docs/`。
- 冲突：靠措辞 + 就近相关性；用户硬规则恒胜。
- `文档/` 与同树旁路 `AgentCore/index/`（code_search；系统噪音）正交：索引管符号检索；导航/主题管叙事路由。勿与 `~/Documents/AgentCore/` 工作区容器混淆。
- 主题继续 `name=主题/<slug>.md`（非真实嵌套 folder）——有意设计。
- **约定常量**：`AgentCore/文档/项目/` → 代码 `workspace/stage_dirs.py`（`PROJECT_DOCS_DIR`）；案卷子目录 `research`/`debate`/`reviews` 同文件。

→ 见代码：`memory/document_store.py`、`memory/migrate_agentcore.py`

---

## 二、注入

1. 工作记忆经 `load_recent_history` 进窗口（CEO / worker 共用）。
2. 长期记忆折叠进共享 `<rules>` 基座：用户规则在前（权威）、AI 记忆在后（软措辞）；无用户规则时与旧 memory-only 块逐字节一致（护前缀缓存）。
3. always 序：**全局偏好 → 全局画像 → 项目画像 → 项目导航**（缺文件跳过）；on_demand 主题只列目录，按需 `consult_memory`（项目优先、全局兜底）。
4. **当前课题认定**（✅）：「继续做项目 / 汇报现状」且用户未点名时，**工作区（及已绑工程）近况 ＞ 全局画像「正在做 X」**——全局仅软参考，不得压过工作区，也不得把旧项目名写进默认提问套用户。偏好/文风等仍可用全局记忆。
5. 注入前剥人面 chrome（H1 + 说明引用块），文件本身不动。
6. 装配顺序权威 → [执行引擎 §七](/docs/03-AI核心/执行引擎架构设计.md) / `runtime/context/`（`SectionOrder`）。

→ 见代码：`memory/rules_injection.py`

---

## 三、维护协议（情景沉淀 → 语义巩固）

| 层 | 触发 | 行为 | 前端 |
|---|---|---|---|
| **情景沉淀** | 每场收尾 | ≤200 字摘要追加；**不注入 prompt** | 轻提示 |
| **语义巩固** | ≥3 场未消化 **或** ≥24h | 整文件重写偏好/画像；主题保留 ops | diff 卡片 |

- 异常回合（cancelled / interrupted / error）跳过沉淀仍推进 watermark。
- 偏好只能来自用户**明示或纠正**，禁止从任务题材推断。
- 空重写 / 保留率 <50% → 拒落盘；巩固失败不标记已消化。
- 用户明示「记住」→ `remember` 直写**用户规则**（`ai_maintained=false`），立即生效。
- 记忆能力**产品层恒开**（无用户总闸）；用户靠文件页编辑/清空控制内容。异常回合仍跳过沉淀并推进 watermark。

### 两种「冷启动」（正交、禁混名）

| | **巩固冷启动** `_is_cold_start` | **冷启动探索幕**（含指纹脏标记 / 旁路重探） |
|---|---|---|
| 闸看 | **全局** `偏好.md`+`画像.md` 皆空 | 见下表「探索触发」 |
| 行为 | 巩固抽取降门槛 | CEO 组队探索 → 合并写项目画像 + **导航** + 主题；禁经 `remember` 落规则 |

#### 探索触发与挡请求（✅ 软硬分层）

| 触发 | 信号 | 与当前用户请求 |
|---|---|---|
| 仅空画像 | 项目 `画像.md` 空（无换绑、无点名、无工程点名短语） | **不挡（软幕）**：软提示可摸仓；域外调研可直接开跑 |
| 空画像 + 工程信号 | 空画像且命中「继续开发 / 改本仓」等**允许表短语**（不扫长文猜意图） | **挡** |
| 换绑 | `explore_workspace_key` ≠ 当前绑定 | **挡** |
| 指纹漂移 | 顶层树 + 关键清单指纹相对上次探索写入已变（README / package·锁文件 / pyproject / 顶层目录名等；**不做**纯天数、**不以** commit 为唯一闸） | **不挡**。一期（R2）✅：脏标记 + 软提示「项目结构已变，可点名刷新」。二期（R1）✅：`schedule_explore_refresh` 旁路静默合并更新（无 team_preview、不占当前对话） |
| 用户点名 | 「先了解 / 重新了解 / 刷新项目记忆」 | **挡**（强制开幕、合并更新；点名硬闸与 pending 同级 ✅） |

**产物谁写（D1）✅**：硬挡 pending 时 worker 可用 `form=files`，但 `write_scope≤explore_memory`（只写 `AgentCore/` 约定记忆/探索笔记；越权在写工具层拒）。画像 / 导航 / 主题收尾仍经 CEO `update_project_profile`（及同族工具）。`文档/项目/` 厚案卷只在探索闸清除后、或普通回合按需落盘——**不**在 pending 探索批内写。R1 旁路亦不经 worker 写用户工程树。**否决**再用禁 `form=files` 代理本约束。

**主题上限（T2）✅**：取消单次硬顶 3；单次探索/更新 **软顶 5**（超额截断+warning）；仓库主题总数仍受 `memory_max_topic_files`（现状 24）约束；多轮探索可累加主题。

**二期 ✅（已落地）**：
- **点名硬闸**：用户原文命中「先了解 / 重新了解 / 刷新项目记忆」等允许短语 → `explore_reason=refresh`，与 rebind /（空画像+工程信号）同级置 pending + `<cold_start_explore>`（合并更新文案）；非意图分类器。
- **R1 旁路**：指纹脏时 `schedule_explore_refresh`（consolidation 同级：debounce、per-folder 互斥、不挡当前回合、无 team_preview）。执行面 = 工作区快照 → memory 档 LLM → 合并写导航/画像（可选主题）→ 更新指纹并清脏；**不是**后台再跑一整场 CEO+delegate 探索幕。
- **`文档/项目/`**：约定目录入权威源（`stage_dirs.PROJECT_DOCS_DIR`）；探索 pending 仍不写；闸清后/普通回合可按需落盘。

**否决仍成立**：不写用户仓根文档；不做向量 chunk 自动灌 prompt；不新建独立 `知识/` 注入层。指纹与「仅空画像」**不**注入 `<cold_start_explore>` 硬挡块（漂移用 `<project_nav_stale>`；仅空画像用软提示）。旧「不做指纹自动重探」改为：一期脏标记、二期旁路（因短入口会过时）。

→ 见代码：`memory/episodic.py`、`memory/explore_profile.py`、`memory/explore_refresh.py`；编排 → [编排器 · 冷启动探索幕](/docs/03-AI核心/编排器与CEO主Agent.md)

---

## 四、跨会话对话日志

Worker 经 `search_conversations` / `read_conversation` 按需检索本账号历史原文（messages + turn_journal）；CEO **只 `delegate` 查阅员**。`search_conversations` 支持 `updated_within_hours`（日复盘等）。用户 `@` 对话附件走服务端 `log_export` 深读。能力**产品层恒开**（无独立隐私闸）；控制面为编辑/清空长期记忆与删除对话，而非总开关。

**系统模板 · 每日对话复盘** ✅：站立任务 `template_key=daily_conversation_review`（引导开、默认日跑）。作用域可配（全局裸聊 / 多云项目 / 回看小时）。**无新料硬闸**：作用域内无近期对话则收件箱直接「今日无新料」、不跑 LLM。有料时代跑 brief 要求 `ask_user card=daily_review`；用户勾选确认后**服务端直接**写记忆 / 用户规则 / `AgentCore/文档/reviews/`（不再依赖 LLM 再调 remember）。与语义巩固并存。→ `standing_tasks/templates.py` · `review_apply.py` · `review_preflight.py`；桌面 Toolbox → 自动化。

**对外口径**（CEO 对用户说话）：白话三层——当前会话 / 偏好与笔记 / 点名可派队员查旧场；不报工具名与内部角色；手头无原文时说明「需要派人去查」再行动，禁止装不知道或空口编造。→ 见代码：`runtime/resolve/prompt.py`（【记忆/历史·对外口径】【跨会话原文】）

→ 见代码：`conversation/log_export.py`、`tools/builtin/search_conversations.py`

---

## 五、其它要点

- **自动标题**：侧边栏 UX，非记忆层；不进 Agent 上下文。云/本地均在首条用户消息可用后并行铸题（只用用户首句，`assistant_reply=""`）。云走 `schedule_title_generation` + SSE `title_generated`；本地 sidecar 无云 SSE，桌面首发并行 `POST …/auto-title`，回合回写仅空标题兜底（`_title_inflight` 时跳过）。禁止首轮后再补铸。
- **会话摘要记忆层已移除**：跨会话情景对 CEO 分工帮助有限；可复用信号由长期记忆承载。两层协议的「情景沉淀」不注入——与本否决不冲突。
- **搜索**：取消向量 RAG 作 prompt 自动注入；agentic 检索（`file_read`/`grep`/`code_search`）为主路。`code_search` = 工具后端（**只查**当前 BM25 快照），索引由回合启动 / 写后后台 `IndexMaintainer` 维护；`building`/`stale` 时模型改用 `grep`。非 RAG 层。
- **远期**：TWM / recall / 委派预算等延后到窗口不足时（DeepSeek 1M 远大于 MVP 用量）。

---

## 六、否决项

| 方案 | 理由 |
|---|---|
| 独立 `user_memory` 表 / `preference` 角色 | 与文件树重叠、对用户黑盒 |
| 单层巩固 + 冷却/门槛 | 只抑症状，不解「单场判断持久性」 |
| 首轮后再补铸标题 | 收益小、二次覆盖复杂 |
| 照搬 Cursor rules（globs 为主入口） | 大众不手写规则文件；对话产品无 globs 附着物 |
| 独立 `AgentCore/知识/` + 知识目录注入 | 无独立可注入知识库产品；案卷走 `文档/` + `file_read` |
| 偏好/画像改 on_demand；隐藏点目录替代可见 `AgentCore/` | 规则缺了模型不会主动查；产品心智要可见约定根 |
| 向量 chunk 自动灌进 prompt | 与「文件随时变」不合；agentic 自取永远新鲜 |
| 用户可关的记忆/历史查阅总闸（设置页） | 默认常开 + 文件页编辑/清空已够；总闸难懂且历史检索与记忆正交却同页堆开关；定案 A 恒开并删页 |

查看/编辑：文件页 `AgentCore/{规则,记忆}/` + CAS；semantic diff 可搬层纠错。→ 见代码：`fileWorkbench/AgentCoreSection.tsx`
