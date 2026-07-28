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
│   └── 主题/<slug>.md    on_demand · consult_memory
└── 文档/                 工作区盘 · 永不进 <rules> · 按需 file_read
```

- 叠加注入：绑定文件夹的对话 = 全局 + 该项目；预算紧张时**全局优先**；项目层无 `偏好.md`。
- 冲突：靠措辞 + 就近相关性；用户硬规则恒胜。
- `文档/` 与 `.agentcore/index/`（code_search）正交，勿与 `~/Documents/AgentCore/` 工作区容器混淆。
- 主题继续 `name=主题/<slug>.md`（非真实嵌套 folder）——有意设计。

→ 见代码：`memory/document_store.py`、`memory/migrate_agentcore.py`

---

## 二、注入

1. 工作记忆经 `load_recent_history` 进窗口（CEO / worker 共用）。
2. 长期记忆折叠进共享 `<rules>` 基座：用户规则在前（权威）、AI 记忆在后（软措辞）；无用户规则时与旧 memory-only 块逐字节一致（护前缀缓存）。
3. always 序：**全局偏好 → 全局画像 → 项目画像**；on_demand 主题只列目录，按需 `consult_memory`（项目优先、全局兜底）。
4. 注入前剥人面 chrome（H1 + 说明引用块），文件本身不动。
5. 装配顺序权威 → [执行引擎 §七](/docs/03-AI核心/执行引擎架构设计.md) / `runtime/context/`（`SectionOrder`）。

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

| | **巩固冷启动** `_is_cold_start` | **冷启动探索幕** |
|---|---|---|
| 闸看 | **全局** `偏好.md`+`画像.md` 皆空 | **项目** `画像.md` 空 **或** `explore_workspace_key` 与当前绑定不一致 |
| 行为 | 巩固抽取降门槛 | CEO 组队探索 → `update_project_profile` 中途直写项目画像（可选 ≤3 主题）；禁经 `remember` 落规则 |

→ 见代码：`memory/episodic.py`、`memory/explore_profile.py`；编排 → [编排器 · 冷启动探索幕](/docs/03-AI核心/编排器与CEO主Agent.md)

---

## 四、跨会话对话日志

Worker 经 `search_conversations` / `read_conversation` 按需检索本账号历史原文（messages + turn_journal）；CEO **只 `delegate` 查阅员**。用户 `@` 对话附件走服务端 `log_export` 深读。能力**产品层恒开**（无独立隐私闸）；控制面为编辑/清空长期记忆与删除对话，而非总开关。

→ 见代码：`conversation/log_export.py`、`tools/builtin/search_conversations.py`

---

## 五、其它要点

- **自动标题**：侧边栏 UX，非记忆层；不进 Agent 上下文。云回合在首条用户消息落库后并行铸题；本地 sidecar 仍回合结束回写。
- **会话摘要记忆层已移除**：跨会话情景对 CEO 分工帮助有限；可复用信号由长期记忆承载。两层协议的「情景沉淀」不注入——与本否决不冲突。
- **搜索**：取消向量 RAG 作 prompt 自动注入；agentic 检索（`file_read`/`grep`/`code_search`）为主路。`code_search` = 工具后端，非 RAG 层。
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
